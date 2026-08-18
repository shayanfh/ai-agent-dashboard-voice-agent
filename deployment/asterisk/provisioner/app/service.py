import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from app.ami import AmiClient
from app.config import Settings
from app.models import (
    ConnectionResponse,
    ConnectionSpec,
    ExtensionResponse,
    ExtensionSpec,
    OutboundCallResponse,
    OutboundCallSpec,
)
from app.renderer import (
    destination_uri,
    extension_route,
    render_dialplan,
    render_pjsip,
    section_id,
)

logger = logging.getLogger(__name__)


class ProvisioningService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ami = AmiClient(settings)
        self.lock = asyncio.Lock()

    def _load(self) -> tuple[dict[str, ConnectionSpec], dict[str, ExtensionSpec]]:
        path = Path(self.settings.state_file)
        if not path.exists():
            return {}, {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "connections" in payload or "extensions" in payload:
            connection_payload = payload.get("connections") or {}
            extension_payload = payload.get("extensions") or {}
        else:
            # Backward compatibility with the original flat connection state file.
            connection_payload = payload
            extension_payload = {}
        return (
            {
                key: ConnectionSpec.model_validate(value)
                for key, value in connection_payload.items()
            },
            {key: ExtensionSpec.model_validate(value) for key, value in extension_payload.items()},
        )

    @staticmethod
    def _atomic_write(path_value: str, content: str, mode: int = 0o600) -> None:
        path = Path(path_value)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    async def _restore(
        self,
        connections: dict[str, ConnectionSpec],
        extensions: dict[str, ExtensionSpec],
    ) -> None:
        try:
            self._render(connections, extensions)
            await self.ami.reload()
        except Exception:
            # Preserve the original provisioning exception while still making
            # the rollback problem visible in the container logs.
            logger.exception("Could not restore the previous FreePBX configuration")

    def _render(
        self,
        connections: dict[str, ConnectionSpec],
        extensions: dict[str, ExtensionSpec],
    ) -> None:
        self._atomic_write(
            self.settings.generated_pjsip_file,
            render_pjsip(connections, self.settings, extensions),
            mode=0o640,
        )
        self._atomic_write(
            self.settings.generated_dialplan_file,
            render_dialplan(connections, self.settings, extensions),
            mode=0o640,
        )

    def _save(
        self,
        connections: dict[str, ConnectionSpec],
        extensions: dict[str, ExtensionSpec],
    ) -> None:
        content = json.dumps(
            {
                "version": 2,
                "connections": {
                    key: value.model_dump(mode="json") for key, value in connections.items()
                },
                "extensions": {
                    key: value.model_dump(mode="json") for key, value in extensions.items()
                },
            },
            indent=2,
            sort_keys=True,
        )
        self._atomic_write(self.settings.state_file, content)

    async def reconcile(self) -> None:
        """Render persisted state after upgrades and load it into Asterisk."""
        async with self.lock:
            connections, extensions = self._load()
            self._render(connections, extensions)
            await self.ami.reload()

    async def upsert(self, connection_id: str, spec: ConnectionSpec) -> ConnectionResponse:
        async with self.lock:
            connections, extensions = self._load()
            previous = dict(connections)
            connections[connection_id] = spec
            try:
                self._render(connections, extensions)
                await self.ami.reload()
                self._save(connections, extensions)
            except Exception:
                await self._restore(previous, extensions)
                raise
        return await self.status(connection_id)

    async def delete(self, connection_id: str) -> bool:
        async with self.lock:
            connections, extensions = self._load()
            if connection_id not in connections:
                return False
            previous = dict(connections)
            del connections[connection_id]
            try:
                self._render(connections, extensions)
                await self.ami.reload()
                self._save(connections, extensions)
            except Exception:
                await self._restore(previous, extensions)
                raise
            return True

    async def status(self, connection_id: str) -> ConnectionResponse:
        connections, _ = self._load()
        spec = connections.get(connection_id)
        if not spec:
            raise KeyError(connection_id)
        state = "configured"
        if spec.mode == "registration":
            output = await self.ami.command(
                f"pjsip show registration {section_id(connection_id)}-registration"
            )
            state = "registered" if "Registered" in output else "unregistered"
        setup = {
            "configured_asterisk": True,
            "provider_action_required": spec.mode == "ip_trunk",
        }
        if spec.mode == "ip_trunk":
            setup.update(
                destination_sip_uri=destination_uri(
                    self.settings.public_sip_uri, spec.phone_number
                ),
                allowed_source_addresses=spec.allowed_addresses,
            )
        return ConnectionResponse(
            resource_id=f"pc-{connection_id}", state=state, provider_setup=setup
        )

    async def upsert_extension(self, extension_id: str, spec: ExtensionSpec) -> ExtensionResponse:
        async with self.lock:
            connections, extensions = self._load()
            previous = dict(extensions)
            extensions[extension_id] = spec
            try:
                self._render(connections, extensions)
                await self.ami.reload()
                self._save(connections, extensions)
            except Exception:
                await self._restore(connections, previous)
                raise
        return ExtensionResponse(
            resource_id=f"ext-{extension_id}",
            state="configured" if spec.enabled else "disabled",
        )

    async def delete_extension(self, extension_id: str) -> bool:
        async with self.lock:
            connections, extensions = self._load()
            if extension_id not in extensions:
                return False
            previous = dict(extensions)
            del extensions[extension_id]
            try:
                self._render(connections, extensions)
                await self.ami.reload()
                self._save(connections, extensions)
            except Exception:
                await self._restore(connections, previous)
                raise
        return True

    async def extension_status(self, extension_id: str) -> ExtensionResponse:
        _, extensions = self._load()
        spec = extensions.get(extension_id)
        if not spec:
            raise KeyError(extension_id)
        return ExtensionResponse(
            resource_id=f"ext-{extension_id}",
            state="configured" if spec.enabled else "disabled",
        )

    async def originate(self, spec: OutboundCallSpec) -> OutboundCallResponse:
        connections, _ = self._load()
        connection = connections.get(str(spec.connection_id))
        if not connection:
            raise ValueError("Outbound phone connection is not provisioned")
        if connection.mode in {"ip_trunk", "twilio"} and not connection.server_uri:
            raise ValueError(
                "This connection has no outbound SIP termination URI; configure server_uri first"
            )
        sid = section_id(str(spec.connection_id))
        room_name = f"outbound-{spec.campaign_id.hex[:12]}-{spec.recipient_id.hex[:12]}"
        variables = {
            "AI_ATTEMPT_ID": str(spec.attempt_id),
            "AI_COMPANY_ID": str(spec.company_id),
            "AI_AGENT_ID": str(spec.agent_id or ""),
            "AI_CAMPAIGN_ID": str(spec.campaign_id),
            "AI_RECIPIENT_ID": str(spec.recipient_id),
            "AI_CALL_ID": str(spec.call_id),
            "AI_CALLER_ID": spec.caller_id,
            "AI_DESTINATION": spec.destination_number,
            "AI_ROOM_NAME": room_name,
            "AI_MEDIA_ID": spec.media_id or "",
        }
        for digit, action in (spec.keypad_actions or {}).items():
            key = {"*": "STAR", "#": "HASH"}.get(digit, digit)
            if action.startswith("extension:"):
                action = extension_route(spec.company_id, action.split(":", 1)[1])
            variables[f"AI_KEY_{key}"] = action
        context = {
            "ai_conversation": "ai-agent-outbound-ai",
            "voice_broadcast": "ai-agent-outbound-broadcast",
            "voice_broadcast_keypad": "ai-agent-outbound-keypad",
        }[spec.campaign_type]
        await self.ami.originate(
            action_id=str(spec.attempt_id),
            channel=f"PJSIP/{spec.destination_number}@{sid}",
            context=context,
            caller_id=spec.caller_id,
            timeout_seconds=spec.ring_timeout_seconds,
            variables=variables,
        )
        return OutboundCallResponse(
            accepted=True,
            provider_call_id=str(spec.attempt_id),
            room_name=room_name if spec.campaign_type == "ai_conversation" else None,
        )
