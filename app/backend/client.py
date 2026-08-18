from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.backend.exceptions import AgentNotFound, BackendRejected, BackendUnavailable
from app.backend.schemas import (
    CallComplete,
    CallCreate,
    CallCreated,
    CallMessage,
    KnowledgeSnapshot,
    ResolvedAgent,
    TransferTarget,
)
from app.core.config import Settings


class _RetryableBackendError(Exception):
    pass


class DashboardBackendClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.dashboard_backend_url.rstrip("/"),
            timeout=settings.http_timeout_seconds,
            headers={
                "X-Internal-API-Key": settings.dashboard_internal_api_key.get_secret_value(),
                "User-Agent": settings.app_name,
            },
        )

    async def __aenter__(self) -> "DashboardBackendClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        headers = {"X-Correlation-ID": correlation_id or str(uuid4())}
        headers["X-Internal-API-Key"] = (
            self._settings.dashboard_internal_api_key.get_secret_value()
        )
        headers["User-Agent"] = self._settings.app_name
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        attempts = self._settings.http_max_retries + 1
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=wait_exponential(multiplier=0.25, min=0.25, max=3),
                retry=retry_if_exception_type(
                    (_RetryableBackendError, httpx.TimeoutException, httpx.NetworkError)
                ),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.request(
                        method, path, params=params, json=json, headers=headers
                    )
                    if response.status_code in {429, 502, 503, 504}:
                        raise _RetryableBackendError(
                            f"temporary backend status {response.status_code}"
                        )
                    return response
        except (_RetryableBackendError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise BackendUnavailable("Dashboard Backend is temporarily unavailable") from exc
        raise BackendUnavailable("Dashboard Backend request exhausted")

    @staticmethod
    def _ensure_success(response: httpx.Response) -> None:
        if response.is_success:
            return
        raise BackendRejected(f"Dashboard Backend rejected request ({response.status_code})")

    async def health(self) -> bool:
        response = await self._request("GET", "/health")
        return response.is_success

    async def resolve_agent(
        self, *, phone_number: str, correlation_id: str
    ) -> ResolvedAgent:
        params = {"phone_number": phone_number}
        response = await self._request(
            "GET", "/api/v1/internal/voice/resolve-agent", params=params,
            correlation_id=correlation_id,
        )
        if response.status_code == 404:
            raise AgentNotFound("No configured agent matches the called number")
        self._ensure_success(response)
        return ResolvedAgent.model_validate(response.json())

    async def resolve_agent_by_id(
        self, *, agent_id: str, company_id: str, call_id: str, correlation_id: str
    ) -> ResolvedAgent:
        response = await self._request(
            "GET",
            "/api/v1/internal/voice/resolve-agent-by-id",
            params={"agent_id": agent_id, "company_id": company_id, "call_id": call_id},
            correlation_id=correlation_id,
        )
        if response.status_code == 404:
            raise AgentNotFound("Outbound campaign agent was not found")
        self._ensure_success(response)
        return ResolvedAgent.model_validate(response.json())

    async def get_knowledge_snapshot(
        self, *, agent_id: str, correlation_id: str
    ) -> KnowledgeSnapshot:
        response = await self._request(
            "GET",
            "/api/v1/internal/voice/knowledge-snapshot",
            params={"agent_id": agent_id},
            correlation_id=correlation_id,
        )
        self._ensure_success(response)
        return KnowledgeSnapshot.model_validate(response.json())

    async def create_call(
        self, data: CallCreate, *, correlation_id: str, idempotency_key: str
    ) -> CallCreated:
        response = await self._request(
            "POST", "/api/v1/internal/voice/calls",
            json=data.model_dump(mode="json"), correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        self._ensure_success(response)
        return CallCreated.model_validate(response.json())

    async def resolve_transfer_target(
        self, call_id: str, target: str, *, correlation_id: str
    ) -> TransferTarget:
        response = await self._request(
            "POST",
            f"/api/v1/internal/voice/calls/{call_id}/transfer-target",
            json={"target": target},
            correlation_id=correlation_id,
        )
        self._ensure_success(response)
        return TransferTarget.model_validate(response.json())

    async def append_call_message(
        self, call_id: str, data: CallMessage, *, correlation_id: str, idempotency_key: str
    ) -> None:
        response = await self._request(
            "POST", f"/api/v1/internal/voice/calls/{call_id}/messages",
            json=data.model_dump(mode="json", exclude_none=True), correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        self._ensure_success(response)

    async def complete_call(
        self, call_id: str, data: CallComplete, *, correlation_id: str
    ) -> None:
        response = await self._request(
            "POST", f"/api/v1/internal/voice/calls/{call_id}/complete",
            json=data.model_dump(mode="json", exclude_none=True), correlation_id=correlation_id,
            idempotency_key=f"complete:{call_id}",
        )
        self._ensure_success(response)
