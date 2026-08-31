from typing import Any, cast

from pytest import MonkeyPatch

from app.backend.schemas import ResolvedAgent
from app.core.config import Settings
from app.providers import factories


def realtime_agent(**overrides: object) -> ResolvedAgent:
    values: dict[str, object] = {
        "company_id": "company-id",
        "agent_id": "agent-id",
        "agent_name": "Realtime Agent",
        "use_realtime": True,
        "voice_id": "selected-elevenlabs-voice",
        "realtime_model": "customer-model-must-be-ignored",
        "tts_model": "customer-tts-model-must-be-ignored",
    }
    values.update(overrides)
    return ResolvedAgent.model_validate(values)


def test_realtime_llm_is_fixed_and_text_only(
    monkeypatch: MonkeyPatch,
    settings: Settings,
) -> None:
    captured: dict[str, object] = {}

    def fake_realtime_model(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "app.providers.factories.openai.realtime.RealtimeModel",
        fake_realtime_model,
    )

    factories.create_realtime_llm(realtime_agent(), settings)

    assert captured["model"] == "gpt-realtime"
    assert captured["modalities"] == ["text"]
    assert captured["api_key"] == "provider-secret"
    transcription = cast(Any, captured["input_audio_transcription"])
    assert transcription.model == "gpt-4o-mini-transcribe"


def test_realtime_tts_uses_selected_elevenlabs_voice(
    monkeypatch: MonkeyPatch,
    settings: Settings,
) -> None:
    captured: dict[str, object] = {}

    def fake_tts(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("app.providers.factories.elevenlabs.TTS", fake_tts)

    factories.create_realtime_tts(realtime_agent(language="fa"), settings)

    assert captured == {
        "model": "eleven_flash_v2_5",
        "voice_id": "selected-elevenlabs-voice",
        "language": "fa",
        "auto_mode": True,
        "api_key": "elevenlabs-secret",
    }
