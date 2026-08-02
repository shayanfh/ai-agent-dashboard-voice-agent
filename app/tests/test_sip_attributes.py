from dataclasses import dataclass, field

from app.telephony.attributes import extract_sip_call_info, parse_remote_sip_headers


@dataclass
class Participant:
    identity: str = "sip-caller-random"
    name: str = "Caller"
    metadata: str = "{}"
    attributes: dict[str, str] = field(
        default_factory=lambda: {
            "sip.phoneNumber": "+96890000000",
            "sip.trunkPhoneNumber": "+96824000000",
            "sip.trunkID": "trunk",
            "sip.callID": "call-id",
            "sip.callIDFull": "asterisk-call-id",
            "asterisk.linkedID": "linked-id",
        }
    )


def test_extracts_numbers_without_assuming_identity() -> None:
    info = extract_sip_call_info(Participant(), room_name="call-abc")
    assert info.caller_number == "+96890000000"
    assert info.called_number == "+96824000000"
    assert info.participant_identity == "sip-caller-random"
    assert info.sip_call_id == "call-id"
    assert info.sip_call_id_full == "asterisk-call-id"
    assert info.asterisk_linked_id == "linked-id"


def test_parse_remote_sip_headers_is_case_insensitive() -> None:
    headers = parse_remote_sip_headers(
        '{"headers":{"X-Asterisk-LinkedID":"abc-123","X-Count":2}}'
    )
    assert headers["x-asterisk-linkedid"] == "abc-123"
    assert headers["x-count"] == "2"


def test_parse_remote_sip_headers_rejects_invalid_payload() -> None:
    assert parse_remote_sip_headers("not-json") == {}
    assert parse_remote_sip_headers('{"headers":[]}') == {}


def test_dispatch_metadata_is_parsed() -> None:
    info = extract_sip_call_info(
        Participant(), room_name="call-abc", job_metadata='{"site":"muscat"}'
    )
    assert info.dispatch_metadata["site"] == "muscat"
