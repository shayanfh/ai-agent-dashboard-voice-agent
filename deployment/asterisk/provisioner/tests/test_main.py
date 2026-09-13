import uuid

import pytest

from app import main
from app.models import OutboundCallResponse, OutboundCallSpec


@pytest.mark.asyncio
async def test_standalone_outbound_call_does_not_register_event_callback(monkeypatch):
    registered = []

    async def originate(_data):
        return OutboundCallResponse(
            accepted=True,
            provider_call_id="standalone-call",
        )

    monkeypatch.setattr(main.outbound_events, "register", registered.append)
    monkeypatch.setattr(main.service, "originate", originate)
    response = await main.originate_outbound_call(
        OutboundCallSpec(
            attempt_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            campaign_type="voice_broadcast",
            destination_number="+96897737034",
            caller_id="+96822388881",
            media_id="a" * 64,
            company_id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            recipient_id=uuid.uuid4(),
            call_id=uuid.uuid4(),
            report_events=False,
        ),
        None,
    )

    assert response.accepted is True
    assert registered == []

