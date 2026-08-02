from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    app_name: str = "ai-agent-dashboard-voice-agent"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    livekit_url: str
    livekit_api_key: SecretStr
    livekit_api_secret: SecretStr
    livekit_agent_name: str = "ai-agent-dashboard-inbound"
    dashboard_backend_url: str
    dashboard_internal_api_key: SecretStr
    default_stt_provider: str = "openai"
    default_stt_model: str = "gpt-4o-mini-transcribe"
    default_llm_provider: str = "openai"
    default_llm_model: str = "gpt-4.1-mini"
    default_tts_provider: str = "openai"
    default_tts_model: str = "gpt-4o-mini-tts"
    default_tts_voice: str = "alloy"
    openai_api_key: SecretStr | None = None
    deepgram_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    summary_llm_model: str = "gpt-5.6-luna"
    summary_llm_timeout_seconds: float = Field(default=20, gt=0, le=120)
    summary_max_transcript_chars: int = Field(default=30_000, ge=1_000, le=200_000)
    summary_max_output_tokens: int = Field(default=400, ge=128, le=2_000)
    http_timeout_seconds: float = Field(default=10, gt=0)
    http_max_retries: int = Field(default=3, ge=0, le=10)
    call_max_duration_seconds: int = Field(default=1800, ge=30)
    caller_wait_timeout_seconds: int = Field(default=30, ge=5)
    enable_call_recording: bool = False
    asterisk_linked_id_wait_seconds: float = Field(default=2.0, ge=0, le=10)
    enable_usage_reporting: bool = True
    enable_debug_logging: bool = False

    @model_validator(mode="after")
    def validate_provider_credentials(self) -> "Settings":
        providers = {
            self.default_stt_provider.lower(),
            self.default_llm_provider.lower(),
            self.default_tts_provider.lower(),
        }
        if "openai" in providers and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for the configured provider pipeline")
        if "deepgram" in providers and not self.deepgram_api_key:
            raise ValueError("DEEPGRAM_API_KEY is required when Deepgram STT is configured")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
