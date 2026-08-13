from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.backend.schemas import ResolvedAgent
from app.telephony.attributes import SipCallInfo


@dataclass(slots=True)
class CallContext:
    call_id: str
    correlation_id: str
    company_id: str
    agent_id: str
    sip: SipCallInfo
    agent_configuration: ResolvedAgent
    sequence_number: int = 0
    request_created: bool = False
    was_transferred: bool = False
    transfer_extension: str | None = None
    completed: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    transcript: list[tuple[str, str]] = field(default_factory=list)
    persisted_message_ids: set[str] = field(default_factory=set)

    def next_sequence(self) -> int:
        self.sequence_number += 1
        return self.sequence_number
