import pytest

from app.core.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        livekit_url="ws://livekit.test",
        livekit_api_key="key",
        livekit_api_secret="secret",
        dashboard_backend_url="http://backend.test",
        dashboard_internal_api_key="internal-secret",
        openai_api_key="provider-secret",
        http_max_retries=1,
    )

