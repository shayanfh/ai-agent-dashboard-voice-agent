import json
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest

from app.agent.context import CallContext
from app.backend.client import DashboardBackendClient
from app.backend.schemas import CallComplete, ResolvedAgent
from app.core.config import Settings
from app.services.call_service import CallLifecycleService
from app.services.summary_service import OpenAICallSummarizer
from app.telephony.attributes import SipCallInfo


def make_context() -> CallContext:
    configuration = ResolvedAgent(
        company_id="company",
        agent_id="agent",
        agent_name="Pizza Agent",
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
            ("caller", "یک پیتزا پپرونی می‌خواهم."),
            ("assistant", "سفارش را ثبت کنم؟"),
            ("caller", "نه، منصرف شدم."),
        ],
    )


@pytest.mark.asyncio
async def test_openai_summarizer_uses_fixed_model_and_full_transcript(
    settings: Settings,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        assert request.headers["Authorization"] == "Bearer provider-secret"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-5.6-luna"
        assert payload["store"] is False
        assert payload["reasoning"] == {"effort": "none"}
        assert payload["text"] == {"verbosity": "low"}
        assert "پیتزا پپرونی" in payload["input"]
        assert "سفارش را ثبت کنم" in payload["input"]
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "کاربر قصد سفارش پیتزا داشت اما در نهایت منصرف شد.",
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
        summary = await OpenAICallSummarizer(settings, client).summarize(
            make_context().transcript
        )

    assert summary == "کاربر قصد سفارش پیتزا داشت اما در نهایت منصرف شد."


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


class FailingSummarizer:
    async def summarize(self, transcript: list[tuple[str, str]]) -> str:
        raise httpx.TimeoutException("summary timed out")


@pytest.mark.asyncio
async def test_call_completion_falls_back_when_summary_llm_fails() -> None:
    backend = FakeBackend()
    lifecycle = CallLifecycleService(
        cast(DashboardBackendClient, backend),
        make_context(),
        FailingSummarizer(),
    )

    await lifecycle.complete(reason="caller_disconnected")

    assert backend.completed is not None
    assert backend.completed.summary == "یک پیتزا پپرونی می‌خواهم. نه، منصرف شدم."
