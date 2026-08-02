from app.agent.context import CallContext
from app.backend.schemas import ResolvedAgent
from app.telephony.attributes import SipCallInfo


def make_context(call_id: str) -> CallContext:
    config = ResolvedAgent(
        company_id=f"company-{call_id}", agent_id="agent", agent_name="Agent"
    )
    sip = SipCallInfo(
        caller_number=None,
        called_number="1000",
        sip_trunk_id=None,
        sip_call_id=None,
        sip_call_id_full=None,
        sip_rule_id=None,
        participant_identity="sip",
        participant_name="",
        destination_extension=None,
        asterisk_linked_id=None,
        room_name="room",
        dispatch_metadata={},
    )
    return CallContext(call_id, "correlation", config.company_id, "agent", sip, config)


def test_call_context_state_is_isolated() -> None:
    first = make_context("one")
    second = make_context("two")
    first.transcript.append(("caller", "private"))
    first.request_created = True
    assert second.transcript == []
    assert second.request_created is False
    assert first.company_id != second.company_id


def test_sequence_is_per_call() -> None:
    first = make_context("one")
    second = make_context("two")
    assert first.next_sequence() == 1
    assert first.next_sequence() == 2
    assert second.next_sequence() == 1
