import asyncio
import logging
import os
import secrets
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Header, HTTPException, Response, UploadFile, status

from app.config import settings
from app.events import OutboundEventMonitor
from app.models import (
    ConnectionResponse,
    ConnectionSpec,
    ExtensionResponse,
    ExtensionSpec,
    OutboundCallResponse,
    OutboundCallSpec,
)
from app.service import ProvisioningService

logger = logging.getLogger(__name__)
app = FastAPI(title="Asterisk Provisioner", docs_url=None, redoc_url=None)
service = ProvisioningService(settings)
outbound_events = OutboundEventMonitor(settings)


@app.on_event("startup")
async def start_outbound_monitor() -> None:
    await outbound_events.start()


@app.on_event("shutdown")
async def stop_outbound_monitor() -> None:
    await outbound_events.stop()


def authenticate(x_provisioner_api_key: str = Header(...)) -> None:
    if not secrets.compare_digest(x_provisioner_api_key, settings.provisioner_api_key):
        raise HTTPException(status_code=401, detail="Invalid provisioner API key")


@app.get("/health")
async def health(_: None = Depends(authenticate)) -> dict:
    return {"status": "ok"}


@app.put("/v1/connections/{connection_id}", response_model=ConnectionResponse)
async def upsert_connection(
    connection_id: uuid.UUID,
    data: ConnectionSpec,
    _: None = Depends(authenticate),
):
    try:
        return await service.upsert(str(connection_id), data)
    except (ValueError, RuntimeError, OSError) as exc:
        logger.exception("FreePBX provisioning failed for connection %s", connection_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/connections/{resource_id}", response_model=ConnectionResponse)
async def get_connection(
    resource_id: str,
    _: None = Depends(authenticate),
):
    try:
        connection_id = str(uuid.UUID(resource_id.removeprefix("pc-")))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Connection not found") from exc
    try:
        return await service.status(connection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Connection not found") from exc


@app.delete("/v1/connections/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    resource_id: str,
    _: None = Depends(authenticate),
) -> Response:
    try:
        connection_id = str(uuid.UUID(resource_id.removeprefix("pc-")))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Connection not found") from exc
    deleted = await service.delete(connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Connection not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.put("/v1/extensions/{extension_id}", response_model=ExtensionResponse)
async def upsert_extension(
    extension_id: uuid.UUID,
    data: ExtensionSpec,
    _: None = Depends(authenticate),
):
    try:
        return await service.upsert_extension(str(extension_id), data)
    except (ValueError, RuntimeError, OSError) as exc:
        logger.exception("FreePBX provisioning failed for extension %s", extension_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/extensions/{resource_id}", response_model=ExtensionResponse)
async def get_extension(
    resource_id: str,
    _: None = Depends(authenticate),
):
    try:
        extension_id = str(uuid.UUID(resource_id.removeprefix("ext-")))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Extension not found") from exc
    try:
        return await service.extension_status(extension_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Extension not found") from exc


@app.delete("/v1/extensions/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extension(
    resource_id: str,
    _: None = Depends(authenticate),
) -> Response:
    try:
        extension_id = str(uuid.UUID(resource_id.removeprefix("ext-")))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Extension not found") from exc
    if not await service.delete_extension(extension_id):
        raise HTTPException(status_code=404, detail="Extension not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.put("/v1/outbound-media/{media_id}")
async def upload_outbound_media(
    media_id: str,
    media: Annotated[UploadFile, File()],
    _: None = Depends(authenticate),
):
    if len(media_id) != 64 or any(char not in "0123456789abcdef" for char in media_id):
        raise HTTPException(status_code=422, detail="Invalid media ID")
    content = await media.read(settings.max_outbound_media_bytes + 1)
    if not content or len(content) > settings.max_outbound_media_bytes:
        raise HTTPException(status_code=413, detail="Outbound media is empty or too large")
    if not content.startswith(b"RIFF") or b"WAVE" not in content[:16]:
        raise HTTPException(status_code=422, detail="Outbound media must be a WAV file")
    await asyncio.to_thread(_write_outbound_media, media_id, content)
    return {"media_id": media_id, "path": f"ai-agent-generated/{media_id}"}


def _write_outbound_media(media_id: str, content: bytes) -> None:
    directory = Path(settings.outbound_media_directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{media_id}.wav"
    temporary = directory / f".{media_id}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(content)
        os.chmod(temporary, 0o640)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


@app.post("/v1/outbound-calls", response_model=OutboundCallResponse, status_code=202)
async def originate_outbound_call(
    data: OutboundCallSpec,
    _: None = Depends(authenticate),
):
    outbound_events.register(str(data.attempt_id))
    try:
        return await service.originate(data)
    except (ValueError, RuntimeError, OSError) as exc:
        outbound_events.unregister(str(data.attempt_id))
        logger.exception("Outbound originate failed for attempt %s", data.attempt_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
