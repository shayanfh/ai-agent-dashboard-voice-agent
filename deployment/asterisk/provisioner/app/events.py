import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class OutboundEventMonitor:
    """Correlate AMI originate/hangup events with Backend outbound attempts."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pending: dict[str, dict] = {}
        self.by_unique_id: dict[str, str] = {}
        self.task: asyncio.Task | None = None
        self.stopping = False

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.backend_outbound_callback_url and self.settings.backend_internal_api_key
        )

    def register(self, attempt_id: str) -> None:
        if not self.enabled:
            return
        self.pending[attempt_id] = {"answered_at": None}

    def unregister(self, attempt_id: str) -> None:
        self.pending.pop(attempt_id, None)

    async def start(self) -> None:
        if self.enabled and not self.task:
            self.task = asyncio.create_task(self._run(), name="ami-outbound-events")

    async def stop(self) -> None:
        self.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def _run(self) -> None:
        while not self.stopping:
            try:
                await self._listen()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("AMI outbound event monitor disconnected")
                await asyncio.sleep(2)

    async def _listen(self) -> None:
        reader, writer = await asyncio.open_connection(
            self.settings.ami_host, self.settings.ami_port
        )
        try:
            await reader.readline()
            writer.write(
                (
                    "Action: Login\r\n"
                    f"Username: {self.settings.ami_username}\r\n"
                    f"Secret: {self.settings.ami_password}\r\n"
                    "Events: on\r\n\r\n"
                ).encode()
            )
            await writer.drain()
            await reader.readuntil(b"\r\n\r\n")
            while not self.stopping:
                raw = await reader.readuntil(b"\r\n\r\n")
                event = self._parse(raw)
                await self._handle(event)
        finally:
            writer.close()
            await writer.wait_closed()

    @staticmethod
    def _parse(raw: bytes) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in raw.decode(errors="replace").split("\r\n"):
            if ": " in line:
                key, value = line.split(": ", 1)
                result[key] = value
        return result

    async def _handle(self, event: dict[str, str]) -> None:
        event_name = event.get("Event")
        if event_name == "UserEvent" and event.get("UserEvent") == "AIOutboundOptOut":
            attempt_id = event.get("AttemptID", "")
            if attempt_id in self.pending:
                await self._callback(
                    attempt_id,
                    "do_not_call",
                    event.get("Uniqueid"),
                    "Recipient opted out by DTMF",
                )
                self.unregister(attempt_id)
                for unique_id, mapped in list(self.by_unique_id.items()):
                    if mapped == attempt_id:
                        self.by_unique_id.pop(unique_id, None)
            return
        if event_name == "OriginateResponse":
            attempt_id = event.get("ActionID", "")
            if attempt_id not in self.pending:
                return
            if event.get("Response") == "Success":
                unique_id = event.get("Uniqueid")
                if unique_id:
                    self.by_unique_id[unique_id] = attempt_id
                self.pending[attempt_id]["answered_at"] = datetime.now(UTC)
                await self._callback(attempt_id, "answered", event.get("Uniqueid"))
            else:
                reason = event.get("Reason", "")
                status = {"5": "busy", "3": "no_answer", "0": "no_answer"}.get(reason, "failed")
                await self._callback(
                    attempt_id,
                    status,
                    event.get("Uniqueid"),
                    f"AMI originate reason {reason}",
                )
                self.unregister(attempt_id)
            return
        if event_name != "Hangup":
            return
        attempt_id = self.by_unique_id.get(event.get("Uniqueid", ""))
        if not attempt_id:
            attempt_id = self.by_unique_id.get(event.get("Linkedid", ""))
        if not attempt_id or attempt_id not in self.pending:
            return
        answered_at = self.pending[attempt_id].get("answered_at")
        duration = int((datetime.now(UTC) - answered_at).total_seconds()) if answered_at else None
        cause = event.get("Cause", "")
        final_status = (
            "completed"
            if answered_at
            else {"17": "busy", "18": "no_answer", "19": "no_answer"}.get(cause, "failed")
        )
        await self._callback(
            attempt_id,
            final_status,
            event.get("Uniqueid"),
            event.get("Cause-txt"),
            duration,
        )
        self.unregister(attempt_id)
        for unique_id, mapped in list(self.by_unique_id.items()):
            if mapped == attempt_id:
                self.by_unique_id.pop(unique_id, None)

    async def _callback(
        self,
        attempt_id: str,
        status: str,
        provider_call_id: str | None = None,
        reason: str | None = None,
        duration_seconds: int | None = None,
    ) -> None:
        payload = {
            "attempt_id": attempt_id,
            "status": status,
            "provider_call_id": provider_call_id,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
            "duration_seconds": duration_seconds,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    self.settings.backend_outbound_callback_url,
                    headers={"X-Internal-API-Key": self.settings.backend_internal_api_key},
                    json=payload,
                )
                response.raise_for_status()
        except Exception:
            logger.exception("Could not deliver outbound event for %s", attempt_id)
