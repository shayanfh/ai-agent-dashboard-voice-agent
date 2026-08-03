from dataclasses import dataclass

import structlog
from livekit import api

from app.backend.client import DashboardBackendClient
from app.backend.schemas import CallRecordingUpdate
from app.core.config import Settings

logger = structlog.get_logger()


@dataclass(slots=True)
class RecordingSession:
    egress_id: str
    object_key: str


class LiveKitRecordingService:
    def __init__(
        self, settings: Settings, backend: DashboardBackendClient
    ) -> None:
        self.settings = settings
        self.backend = backend

    def _client(self) -> api.LiveKitAPI:
        return api.LiveKitAPI(
            self.settings.livekit_url,
            self.settings.livekit_api_key.get_secret_value(),
            self.settings.livekit_api_secret.get_secret_value(),
        )

    async def start(
        self, *, room_name: str, company_id: str, call_id: str
    ) -> RecordingSession:
        object_key = f"recordings/livekit/{company_id}/{call_id}.ogg"
        client = self._client()
        try:
            info = await client.egress.start_room_composite_egress(
                api.RoomCompositeEgressRequest(
                    room_name=room_name,
                    audio_only=True,
                    file_outputs=[
                        api.EncodedFileOutput(
                            file_type=api.EncodedFileType.OGG,
                            filepath=object_key,
                            s3=api.S3Upload(
                                endpoint=self.settings.recording_s3_endpoint or "",
                                access_key=self.settings.recording_s3_access_key.get_secret_value(),
                                secret=self.settings.recording_s3_secret_key.get_secret_value(),
                                bucket=self.settings.recording_s3_bucket,
                                region=self.settings.recording_s3_region,
                                force_path_style=True,
                            ),
                        )
                    ],
                )
            )
            return RecordingSession(egress_id=info.egress_id, object_key=object_key)
        finally:
            await client.aclose()

    async def stop_and_report(
        self,
        session: RecordingSession,
        *,
        call_id: str,
        correlation_id: str,
    ) -> None:
        client = self._client()
        try:
            try:
                info = await client.egress.stop_egress(
                    api.StopEgressRequest(egress_id=session.egress_id)
                )
            except Exception:
                result = await client.egress.list_egress(
                    api.ListEgressRequest(egress_id=session.egress_id)
                )
                if not result.items:
                    raise
                info = result.items[0]
        finally:
            await client.aclose()

        duration_seconds = None
        if info.file_results:
            duration_ns = info.file_results[0].duration
            duration_seconds = max(0, round(duration_ns / 1_000_000_000))
        await self.backend.update_call_recording(
            call_id,
            CallRecordingUpdate(
                egress_id=session.egress_id,
                recording_url=(
                    f"s3://{self.settings.recording_s3_bucket}/{session.object_key}"
                ),
                object_key=session.object_key,
                recording_duration_seconds=duration_seconds,
            ),
            correlation_id=correlation_id,
        )
