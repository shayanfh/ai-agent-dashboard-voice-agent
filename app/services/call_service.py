from datetime import UTC, datetime

import structlog

from app.agent.context import CallContext
from app.backend.client import DashboardBackendClient
from app.backend.schemas import CallComplete

logger = structlog.get_logger()


class CallLifecycleService:
    def __init__(self, backend: DashboardBackendClient, context: CallContext) -> None:
        self.backend = backend
        self.context = context

    async def complete(self, *, reason: str, outcome: str = "no_action") -> None:
        if self.context.completed:
            return
        self.context.completed = True
        ended = datetime.now(UTC)
        duration = max(0, int((ended - self.context.started_at).total_seconds()))
        summary = self._summary()
        try:
            await self.backend.complete_call(
                self.context.call_id,
                CallComplete(
                    summary=summary,
                    outcome=outcome,
                    was_transferred=self.context.was_transferred,
                    transfer_number=(
                        self.context.agent_configuration.transfer_number
                        if self.context.was_transferred else None
                    ),
                    ended_at=ended,
                    duration_seconds=duration,
                    extracted_data={"completion_reason": reason},
                ),
                correlation_id=self.context.correlation_id,
            )
        except Exception:
            logger.exception("call_completion_failed", reason=reason)

    def _summary(self) -> str:
        caller_lines = [text for role, text in self.context.transcript if role == "caller"]
        if not caller_lines:
            return "Call ended without a committed caller message."
        content = " ".join(caller_lines)
        return content[:1000]
