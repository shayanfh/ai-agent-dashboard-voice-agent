from datetime import UTC, datetime

import structlog

from app.agent.context import CallContext
from app.backend.client import DashboardBackendClient
from app.backend.schemas import CallComplete
from app.services.summary_service import CallAnalysis, CallAnalyzer

logger = structlog.get_logger()


class CallLifecycleService:
    def __init__(
        self,
        backend: DashboardBackendClient,
        context: CallContext,
        analyzer: CallAnalyzer,
    ) -> None:
        self.backend = backend
        self.context = context
        self.analyzer = analyzer

    async def complete(self, *, reason: str) -> None:
        if self.context.completed:
            return
        self.context.completed = True
        ended = datetime.now(UTC)
        duration = max(0, int((ended - self.context.started_at).total_seconds()))
        try:
            analysis = await self.analyzer.analyze(self.context.transcript)
            used_fallback = False
        except Exception as exc:
            logger.warning(
                "call_analysis_failed",
                call_id=self.context.call_id,
                error_type=type(exc).__name__,
            )
            analysis = CallAnalysis(
                summary=self._fallback_summary(),
                outcome="no_action",
            )
            used_fallback = True
        logger.info(
            "call_analysis_completed",
            call_id=self.context.call_id,
            outcome=analysis.outcome,
            used_fallback=used_fallback,
        )
        extracted_data = {
            **analysis.extracted_data,
            "completion_reason": reason,
        }
        if (
            analysis.outcome in {"booking_created", "callback_requested"}
            and not extracted_data.get("customer_phone")
            and self.context.sip.caller_number
        ):
            extracted_data["customer_phone"] = self.context.sip.caller_number
        try:
            await self.backend.complete_call(
                self.context.call_id,
                CallComplete(
                    summary=analysis.summary,
                    outcome=analysis.outcome,
                    was_transferred=self.context.was_transferred,
                    transfer_number=(
                        self.context.agent_configuration.transfer_number
                        if self.context.was_transferred else None
                    ),
                    ended_at=ended,
                    duration_seconds=duration,
                    extracted_data=extracted_data,
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
