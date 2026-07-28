from typing import Any

from livekit.plugins import deepgram, openai, silero

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


def create_tts(config: ResolvedAgent, settings: Settings) -> Any:
    provider = (
        config.tts_provider or config.voice_provider or settings.default_tts_provider
    ).lower()
    model = config.tts_model or settings.default_tts_model
    voice = config.voice_id or settings.default_tts_voice
    if provider == "openai":
        return openai.TTS(model=model, voice=voice)
    raise ConfigurationError(f"Unsupported TTS provider: {provider}")


def create_vad() -> Any:
    return silero.VAD.load()
