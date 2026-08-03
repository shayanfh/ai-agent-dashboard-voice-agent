from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.recording_service import LiveKitRecordingService


class FakeBackend:
    def __init__(self) -> None:
        self.update = None

    async def update_call_recording(self, call_id, data, *, correlation_id):
        self.update = (call_id, data, correlation_id)


class FakeEgress:
    def __init__(self) -> None:
        self.start_request = None
        self.stop_request = None

    async def start_room_composite_egress(self, request):
        self.start_request = request
        return SimpleNamespace(egress_id="EG_test")

    async def stop_egress(self, request):
        self.stop_request = request
        return SimpleNamespace(
            file_results=[SimpleNamespace(duration=12_400_000_000)]
        )


class FakeLiveKitClient:
    def __init__(self) -> None:
        self.egress = FakeEgress()
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_livekit_recording_uploads_and_reports(settings: Settings) -> None:
    configured = settings.model_copy(
        update={
            "recording_provider": "livekit_egress",
            "recording_s3_endpoint": "https://storage.test",
            "recording_s3_access_key": settings.livekit_api_key,
            "recording_s3_secret_key": settings.livekit_api_secret,
            "recording_s3_bucket": "recordings",
        }
    )
    backend = FakeBackend()
    service = LiveKitRecordingService(configured, backend)  # type: ignore[arg-type]
    clients: list[FakeLiveKitClient] = []

    def client_factory() -> FakeLiveKitClient:
        client = FakeLiveKitClient()
        clients.append(client)
        return client

    service._client = client_factory  # type: ignore[method-assign]
    session = await service.start(
        room_name="call-room", company_id="company", call_id="call"
    )
    await service.stop_and_report(
        session, call_id="call", correlation_id="correlation"
    )

    request = clients[0].egress.start_request
    assert request.audio_only is True
    assert request.file_outputs[0].filepath == "recordings/livekit/company/call.ogg"
    assert request.file_outputs[0].s3.force_path_style is True
    assert all(client.closed for client in clients)
    assert backend.update[0] == "call"
    assert backend.update[1].recording_duration_seconds == 12
    assert backend.update[1].object_key == "recordings/livekit/company/call.ogg"


def test_livekit_recording_requires_storage_credentials(settings: Settings) -> None:
    with pytest.raises(ValueError, match="RECORDING_S3_ENDPOINT"):
        Settings(
            app_env="test",
            livekit_url="ws://livekit.test",
            livekit_api_key="key",
            livekit_api_secret="secret",
            dashboard_backend_url="http://backend.test",
            dashboard_internal_api_key="internal-secret",
            openai_api_key="provider-secret",
            recording_provider="livekit_egress",
        )
