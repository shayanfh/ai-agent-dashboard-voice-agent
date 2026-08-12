import logging
import secrets
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status

from app.config import settings
from app.models import ConnectionResponse, ConnectionSpec
from app.service import ProvisioningService

logger = logging.getLogger(__name__)
app = FastAPI(title="Asterisk Provisioner", docs_url=None, redoc_url=None)
service = ProvisioningService(settings)


def authenticate(x_provisioner_api_key: str = Header(...)) -> None:
    if not secrets.compare_digest(
        x_provisioner_api_key, settings.provisioner_api_key
    ):
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
        logger.exception(
            "FreePBX provisioning failed for connection %s", connection_id
        )
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
