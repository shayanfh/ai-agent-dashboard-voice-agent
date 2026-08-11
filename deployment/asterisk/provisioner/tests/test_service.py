import json
import uuid

import pytest
from app.config import Settings
from app.models import ConnectionSpec
from app.service import ProvisioningService


class FakeAmi:
    def __init__(self) -> None:
        self.reload_count = 0

    async def reload(self) -> None:
        self.reload_count += 1

    async def command(self, command: str) -> str:
        return "Registration/Server  Auth  Status\nprovider.test  Registered"


@pytest.mark.asyncio
async def test_upsert_status_and_delete_are_atomic(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        provisioner_api_key="test-key",
        public_sip_uri="sip:asterisk.test:5061;transport=tls",
        livekit_sip_uri="sip:livekit.test:5061;transport=tls",
        ami_username="provisioner",
        ami_password="secret",
        state_file=str(tmp_path / "state.json"),
        generated_pjsip_file=str(tmp_path / "pjsip.conf"),
        generated_dialplan_file=str(tmp_path / "extensions.conf"),
        enable_recording=False,
    )
    service = ProvisioningService(settings)
    service.ami = FakeAmi()
    connection_id = str(uuid.uuid4())
    spec = ConnectionSpec(
        company_id=uuid.uuid4(),
        name="Provider registration",
        provider="generic_sip",
        mode="registration",
        phone_number="+19714361744",
        server_uri="provider.test",
        auth_username="customer-1",
        auth_password="provider-secret",
        public_sip_uri=settings.public_sip_uri,
    )

    response = await service.upsert(connection_id, spec)

    assert response.resource_id == f"pc-{connection_id}"
    assert response.state == "registered"
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved[connection_id]["mode"] == "registration"
    assert await service.delete(connection_id) is True
    assert json.loads((tmp_path / "state.json").read_text()) == {}
    assert service.ami.reload_count == 2
