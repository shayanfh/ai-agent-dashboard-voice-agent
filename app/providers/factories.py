from typing import Any

from livekit.plugins import deepgram, elevenlabs, openai, silero
from openai.types import realtime as openai_realtime

from app.backend.schemas import ResolvedAgent
from app.core.config import Settings
from app.core.exceptions import ConfigurationError


def create_stt(config: ResolvedAgent, settings: Settings) -> Any:
    provider = (config.stt_provider or settings.default_stt_provider).lower()
    model = config.stt_model or settings.default_stt_model
    if provider == "openai":
        return openai.STT(model=model, language=config.language)
    if provider == "deepgram":
        return deepgram.STT(model=model, language=config.language)
    raise ConfigurationError(f"Unsupported STT provider: {provider}")


def create_llm(config: ResolvedAgent, settings: Settings) -> Any:
    provider = (config.llm_provider or settings.default_llm_provider).lower()
    model = config.llm_model or settings.default_llm_model
    if provider == "openai":
        return openai.LLM(model=model)
    raise ConfigurationError(f"Unsupported LLM provider: {provider}")


def create_realtime_llm(config: ResolvedAgent, settings: Settings) -> Any:
    """Create the server-owned OpenAI Realtime text-response model.

    Audio is sent directly to the Realtime API. Responses stay text-only so the
    selected ElevenLabs voice can synthesize the final audio stream.
    """
    if not settings.openai_api_key:
        raise ConfigurationError("OPENAI_API_KEY is required for Realtime agents")
    return openai.realtime.RealtimeModel(
        model=settings.realtime_model,
        modalities=["text"],
        input_audio_transcription=openai_realtime.AudioTranscription(
            model=settings.realtime_input_transcription_model,
        ),
        api_key=settings.openai_api_key.get_secret_value(),
    )


def create_tts(config: ResolvedAgent, settings: Settings) -> Any:
    provider = (
        config.tts_provider or config.voice_provider or settings.default_tts_provider
    ).lower()
    model = config.tts_model or settings.default_tts_model
    voice = config.voice_id or settings.default_tts_voice
    if provider == "openai":
        return openai.TTS(model=model, voice=voice)
    if provider == "elevenlabs":
        if not settings.elevenlabs_api_key:
            raise ConfigurationError("ELEVENLABS_API_KEY is required for ElevenLabs TTS")
        return elevenlabs.TTS(
            model=model,
            voice_id=voice,
            language=config.language,
            auto_mode=True,
            api_key=settings.elevenlabs_api_key.get_secret_value(),
        )
    raise ConfigurationError(f"Unsupported TTS provider: {provider}")


def create_realtime_tts(config: ResolvedAgent, settings: Settings) -> Any:
    if not settings.elevenlabs_api_key:
        raise ConfigurationError("ELEVENLABS_API_KEY is required for Realtime agents")
    return elevenlabs.TTS(
        model=settings.realtime_tts_model,
        voice_id=config.voice_id or settings.realtime_tts_voice,
        language=config.language,
        auto_mode=True,
        api_key=settings.elevenlabs_api_key.get_secret_value(),
    )


def create_vad() -> Any:
    return silero.VAD.load()
