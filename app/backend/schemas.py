from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResolvedAgent(BaseModel):
    company_id: str
    agent_id: str
    agent_name: str
    language: str = "en"
    greeting_message: str | None = None
    system_prompt: str | None = None
    transfer_number: str | None = None
    use_realtime: bool = False
    realtime_provider: str | None = None
    realtime_model: str | None = None
    voice_provider: str | None = None
    voice_id: str | None = None
    tts_provider: str | None = None
    tts_model: str | None = None
    stt_provider: str | None = None
    stt_model: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


class CallCreate(BaseModel):
    phone_number: str
    extension: str | None = None
    caller_number: str | None = None
    livekit_room_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CallCreated(BaseModel):
    call_id: str
    company_id: str
    agent_id: str | None
    status: str


class Speaker(StrEnum):
    CALLER = "caller"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class CallMessage(BaseModel):
    speaker: Speaker
    text: str = Field(min_length=1, max_length=20_000)
    sequence: int = Field(ge=1)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class CallComplete(BaseModel):
    summary: str | None = None
    outcome: Literal[
        "booking_created",
        "information_request",
        "callback_requested",
        "no_action",
        "failed",
    ] = "no_action"
    was_transferred: bool = False
    transfer_number: str | None = None
    extracted_data: dict[str, Any] | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)

