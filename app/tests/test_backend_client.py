import httpx
import pytest

from app.backend.client import DashboardBackendClient
from app.backend.exceptions import AgentNotFound
from app.backend.schemas import CallCreate
from app.core.config import Settings


@pytest.mark.asyncio
async def test_resolve_agent_by_called_number(settings: Settings) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Internal-API-Key"] == "internal-secret"
        assert request.url.params["phone_number"] == "+96824000000"
        return httpx.Response(
            200,
            json={
                "company_id": "company",
                "agent_id": "agent",
                "agent_name": "Rental",
                "language": "en",
                "use_realtime": False,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://backend.test"
    ) as http_client:
        client = DashboardBackendClient(settings, http_client)
        result = await client.resolve_agent(
            phone_number="+96824000000", correlation_id="correlation"
        )
    assert result.agent_id == "agent"


@pytest.mark.asyncio
async def test_resolve_agent_not_found(settings: Settings) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(404, json={"error": "not found"}))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://backend.test"
    ) as http_client:
        client = DashboardBackendClient(settings, http_client)
        with pytest.raises(AgentNotFound):
            await client.resolve_agent(phone_number="404", correlation_id="c")


@pytest.mark.asyncio
async def test_create_call_uses_idempotency_key(settings: Settings) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Idempotency-Key"] == "sip-call-1"
        return httpx.Response(
            201,
            json={
                "call_id": "call",
                "company_id": "company",
                "agent_id": "agent",
                "status": "ringing",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://backend.test"
    ) as http_client:
        result = await DashboardBackendClient(settings, http_client).create_call(
            CallCreate(phone_number="1000"),
            correlation_id="c",
            idempotency_key="sip-call-1",
        )
    assert result.call_id == "call"


@pytest.mark.asyncio
async def test_resolve_transfer_target_uses_internal_call_scope(settings: Settings) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/calls/call-1/transfer-target")
        assert request.method == "POST"
        assert request.content == b'{"extension":"100"}'
        return httpx.Response(
            200,
            json={
                "extension_id": "extension-id",
                "extension": "100",
                "display_name": "Sales",
                "sip_uri": "sip:tenant-route@pbx.test:5060;transport=udp",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://backend.test"
    ) as http_client:
        result = await DashboardBackendClient(
            settings, http_client
        ).resolve_transfer_target("call-1", "100", correlation_id="c")
    assert result.extension == "100"
    assert result.sip_uri.startswith("sip:tenant-route@")
