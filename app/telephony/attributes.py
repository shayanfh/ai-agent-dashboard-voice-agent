import json
from dataclasses import dataclass
from typing import Any, Protocol


class ParticipantLike(Protocol):
    @property
    def identity(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def metadata(self) -> str: ...

    @property
    def attributes(self) -> dict[str, str]: ...


ATTRIBUTE_ALIASES: dict[str, tuple[str, ...]] = {
    "caller_number": ("sip.phoneNumber", "sip.callerNumber", "caller_number"),
    "called_number": ("sip.trunkPhoneNumber", "sip.calledNumber", "called_number"),
    "sip_trunk_id": ("sip.trunkID", "sip.trunkId", "sip_trunk_id"),
    "sip_call_id": ("sip.callID", "sip.callId", "sip_call_id"),
    "sip_call_id_full": ("sip.callIDFull", "sip.callIdFull", "sip_call_id_full"),
    "sip_rule_id": ("sip.ruleID", "sip.ruleId", "sip_rule_id"),
    "destination_extension": (
        "sip.extension",
        "sip.destinationExtension",
        "destination_extension",
    ),
    "asterisk_linked_id": (
        "asterisk.linkedID",
        "asterisk.linkedId",
        "asterisk_linked_id",
    ),
}


@dataclass(frozen=True, slots=True)
class SipCallInfo:
    caller_number: str | None
    called_number: str | None
    sip_trunk_id: str | None
    sip_call_id: str | None
    sip_call_id_full: str | None
    sip_rule_id: str | None
    participant_identity: str
    participant_name: str
    destination_extension: str | None
    asterisk_linked_id: str | None
    room_name: str
    dispatch_metadata: dict[str, Any]

    @property
    def routing_number(self) -> str | None:
        return self.called_number or self.destination_extension


def _value(attributes: dict[str, str], field: str) -> str | None:
    return next((attributes[key] for key in ATTRIBUTE_ALIASES[field] if attributes.get(key)), None)


def parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"value": value}
    except json.JSONDecodeError:
        return {"value": raw[:1000]}


def parse_remote_sip_headers(raw: str) -> dict[str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    headers = payload.get("headers") if isinstance(payload, dict) else None
    if not isinstance(headers, dict):
        return {}
    return {
        str(name).lower(): str(value)
        for name, value in headers.items()
        if isinstance(value, (str, int, float))
    }


def extract_sip_call_info(
    participant: ParticipantLike, *, room_name: str, job_metadata: str | None = None
) -> SipCallInfo:
    attrs = participant.attributes
    participant_metadata = parse_metadata(participant.metadata)
    dispatch_metadata = parse_metadata(job_metadata)
    dispatch_metadata.setdefault("participant", participant_metadata)
    return SipCallInfo(
        caller_number=_value(attrs, "caller_number"),
        called_number=_value(attrs, "called_number"),
        sip_trunk_id=_value(attrs, "sip_trunk_id"),
        sip_call_id=_value(attrs, "sip_call_id"),
        sip_call_id_full=_value(attrs, "sip_call_id_full"),
        sip_rule_id=_value(attrs, "sip_rule_id"),
        participant_identity=participant.identity,
        participant_name=participant.name,
        destination_extension=_value(attrs, "destination_extension"),
        asterisk_linked_id=_value(attrs, "asterisk_linked_id"),
        room_name=room_name,
        dispatch_metadata=dispatch_metadata,
    )
