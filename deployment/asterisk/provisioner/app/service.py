import asyncio
import json
import os
from pathlib import Path

from app.ami import AmiClient
from app.config import Settings
from app.models import ConnectionResponse, ConnectionSpec
from app.renderer import destination_uri, render_dialplan, render_pjsip, section_id


class ProvisioningService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ami = AmiClient(settings)
        self.lock = asyncio.Lock()

    def _load(self) -> dict[str, ConnectionSpec]:
        path = Path(self.settings.state_file)
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {key: ConnectionSpec.model_validate(value) for key, value in payload.items()}

    @staticmethod
    def _atomic_write(path_value: str, content: str, mode: int = 0o600) -> None:
        path = Path(path_value)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(content, encoding="utf-8")
        os.chmod(temporary, mode)
        os.replace(temporary, path)

    def _render(self, connections: dict[str, ConnectionSpec]) -> None:
        self._atomic_write(
            self.settings.generated_pjsip_file,
            render_pjsip(connections, self.settings),
            mode=0o640,
        )
        self._atomic_write(
            self.settings.generated_dialplan_file,
            render_dialplan(connections, self.settings),
            mode=0o640,
        )

    def _save(self, connections: dict[str, ConnectionSpec]) -> None:
        content = json.dumps(
            {key: value.model_dump(mode="json") for key, value in connections.items()},
            indent=2,
            sort_keys=True,
        )
        self._atomic_write(self.settings.state_file, content)

    async def upsert(self, connection_id: str, spec: ConnectionSpec) -> ConnectionResponse:
        async with self.lock:
            connections = self._load()
            previous = dict(connections)
            connections[connection_id] = spec
            try:
                self._render(connections)
                await self.ami.reload()
                self._save(connections)
            except Exception:
                self._render(previous)
                try:
                    await self.ami.reload()
                except Exception:
                    pass
                raise
        return await self.status(connection_id)

    async def delete(self, connection_id: str) -> bool:
        async with self.lock:
            connections = self._load()
            if connection_id not in connections:
                return False
            previous = dict(connections)
            del connections[connection_id]
            try:
                self._render(connections)
                await self.ami.reload()
                self._save(connections)
            except Exception:
                self._render(previous)
                try:
                    await self.ami.reload()
                except Exception:
                    pass
                raise
            return True

    async def status(self, connection_id: str) -> ConnectionResponse:
        spec = self._load().get(connection_id)
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
