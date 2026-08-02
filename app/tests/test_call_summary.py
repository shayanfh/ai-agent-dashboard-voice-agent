import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest

from app.agent.context import CallContext
from app.backend.client import DashboardBackendClient
from app.backend.schemas import CallComplete, ResolvedAgent
from app.core.config import Settings
from app.services.call_service import CallLifecycleService
from app.services.summary_service import CallAnalysis, OpenAICallAnalyzer
from app.telephony.attributes import SipCallInfo


def make_context() -> CallContext:
    configuration = ResolvedAgent(
        company_id="company",
        agent_id="agent",
        agent_name="Restaurant Agent",
    )
    sip = SipCallInfo(
        caller_number="+989120000000",
        called_number="1000",
        sip_trunk_id=None,
        sip_call_id=None,
        sip_call_id_full=None,
        sip_rule_id=None,
        participant_identity="sip-caller",
        participant_name="Caller",
        destination_extension=None,
        asterisk_linked_id=None,
        room_name="call-room",
        dispatch_metadata={},
    )
    return CallContext(
        call_id="call-id",
        correlation_id="correlation-id",
        company_id="company",
        agent_id="agent",
        sip=sip,
        agent_configuration=configuration,
        started_at=datetime.now(UTC),
        transcript=[
            ("caller", "I want a table for four tomorrow at 8 PM."),
            ("assistant", "Your reservation request is confirmed."),
            ("caller", "Yes, that is correct."),
        ],
    )


@pytest.mark.asyncio
async def test_openai_analyzer_returns_structured_outcome_and_data(
    settings: Settings,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        assert request.headers["Authorization"] == "Bearer provider-secret"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-5.6-luna"
        assert payload["store"] is False
        assert payload["reasoning"] == {"effort": "none"}
        assert payload["text"]["verbosity"] == "low"
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"]["strict"] is True
        assert "table for four" in payload["input"]
        analysis = {
            "summary": "The caller confirmed a table reservation for four.",
            "outcome": "booking_created",
            "request_type": "table_reservation",
            "customer_name": "",
            "customer_phone": "",
            "facts": [
                {"key": "guest_count", "value": "4"},
                {"key": "reservation_time", "value": "20:00"},
            ],
        }
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(analysis),
                            }
                        ],
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.openai.com",
    ) as client:
        analysis = await OpenAICallAnalyzer(settings, client).analyze(
            make_context().transcript
        )

    assert analysis.summary == "The caller confirmed a table reservation for four."
    assert analysis.outcome == "booking_created"
    assert analysis.extracted_data == {
        "guest_count": "4",
        "reservation_time": "20:00",
        "request_type": "table_reservation",
    }


class FakeBackend:
    def __init__(self) -> None:
        self.completed: CallComplete | None = None

    async def complete_call(
        self,
        call_id: str,
        data: CallComplete,
        *,
        correlation_id: str,
    ) -> None:
        self.completed = data


class FakeAnalyzer:
    async def analyze(self, transcript: Sequence[tuple[str, str]]) -> CallAnalysis:
        return CallAnalysis(
            summary="The caller confirmed a table reservation.",
            outcome="booking_created",
            extracted_data={"request_type": "table_reservation"},
        )


class FailingAnalyzer:
    async def analyze(self, transcript: Sequence[tuple[str, str]]) -> CallAnalysis:
        raise httpx.TimeoutException("analysis timed out")


@pytest.mark.asyncio
async def test_call_completion_persists_outcome_and_uses_caller_phone() -> None:
    backend = FakeBackend()
    lifecycle = CallLifecycleService(
        cast(DashboardBackendClient, backend),
        make_context(),
        FakeAnalyzer(),
    )

    await lifecycle.complete(reason="caller_disconnected")

    assert backend.completed is not None
    assert backend.completed.outcome == "booking_created"
    assert backend.completed.extracted_data == {
        "request_type": "table_reservation",
        "completion_reason": "caller_disconnected",
        "customer_phone": "+989120000000",
    }


@pytest.mark.asyncio
async def test_call_completion_falls_back_when_analysis_fails() -> None:
    backend = FakeBackend()
    lifecycle = CallLifecycleService(
        cast(DashboardBackendClient, backend),
        make_context(),
        FailingAnalyzer(),
    )

    await lifecycle.complete(reason="caller_disconnected")

    assert backend.completed is not None
    assert backend.completed.outcome == "no_action"
    assert backend.completed.summary == (
        "I want a table for four tomorrow at 8 PM. Yes, that is correct."
    )
