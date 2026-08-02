from datetime import UTC, datetime

import structlog

from app.agent.context import CallContext
from app.backend.client import DashboardBackendClient
from app.backend.schemas import CallComplete
from app.services.summary_service import SummaryGenerator

logger = structlog.get_logger()


class CallLifecycleService:
    def __init__(
        self,
        backend: DashboardBackendClient,
        context: CallContext,
        summarizer: SummaryGenerator,
    ) -> None:
        self.backend = backend
        self.context = context
        self.summarizer = summarizer

    async def complete(self, *, reason: str, outcome: str = "no_action") -> None:
        if self.context.completed:
            return
        self.context.completed = True
        ended = datetime.now(UTC)
        duration = max(0, int((ended - self.context.started_at).total_seconds()))
        try:
            summary = await self.summarizer.summarize(self.context.transcript)
        except Exception as exc:
            logger.warning(
                "call_summary_generation_failed",
                call_id=self.context.call_id,
                error_type=type(exc).__name__,
            )
            summary = self._fallback_summary()
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

    def _fallback_summary(self) -> str:
        caller_lines = [text for role, text in self.context.transcript if role == "caller"]
        if not caller_lines:
            return "Call ended without a committed caller message."
        content = " ".join(caller_lines)
        return content[:1000]
