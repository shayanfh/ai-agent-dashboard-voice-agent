import asyncio
from typing import Any

import structlog

from app.agent.context import CallContext
from app.backend.client import DashboardBackendClient
from app.backend.schemas import CallMessage, Speaker

logger = structlog.get_logger()


class TranscriptService:
    def __init__(self, backend: DashboardBackendClient, context: CallContext) -> None:
        self.backend = backend
        self.context = context
        self._pending: set[asyncio.Task[None]] = set()

    def handle_item(self, item: Any) -> None:
        role = getattr(item, "role", None)
        text = (getattr(item, "text_content", None) or "").strip()
        message_id = str(getattr(item, "id", f"{role}:{text}"))
        if not text or role not in {"user", "assistant", "system"}:
            return
        if message_id in self.context.persisted_message_ids:
            return
        self.context.persisted_message_ids.add(message_id)
        speaker = {
            "user": Speaker.CALLER,
            "assistant": Speaker.ASSISTANT,
            "system": Speaker.SYSTEM,
        }[role]
        sequence = self.context.next_sequence()
        self.context.transcript.append((speaker.value, text))
        task = asyncio.create_task(
            self._persist(
                CallMessage(speaker=speaker, text=text, sequence=sequence),
                message_id=message_id,
            )
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _persist(self, message: CallMessage, *, message_id: str) -> None:
        try:
            await self.backend.append_call_message(
                self.context.call_id,
                message,
                correlation_id=self.context.correlation_id,
                idempotency_key=(
                    f"message:{self.context.call_id}:{message.sequence}:{message.speaker}:{message_id}"
                ),
            )
        except Exception:
            logger.exception("transcript_persistence_failed", sequence=message.sequence)

    async def flush(self) -> None:
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
