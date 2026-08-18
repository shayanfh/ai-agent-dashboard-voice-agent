import json
import uuid

import pytest
from app.config import Settings
from app.models import ConnectionSpec, ExtensionSpec, OutboundCallSpec
from app.service import ProvisioningService


class FakeAmi:
    def __init__(self) -> None:
        self.reload_count = 0

    async def reload(self) -> None:
        self.reload_count += 1

    async def command(self, command: str) -> str:
        return "Registration/Server  Auth  Status\nprovider.test  Registered"

    async def originate(self, **kwargs) -> None:
        self.originate_kwargs = kwargs


class FailingAmi(FakeAmi):
    async def reload(self) -> None:
        raise RuntimeError("original AMI reload failure")


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
    assert saved["connections"][connection_id]["mode"] == "registration"
    assert await service.delete(connection_id) is True
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["connections"] == {}
    assert saved["extensions"] == {}
    assert service.ami.reload_count == 2


@pytest.mark.asyncio
async def test_rollback_does_not_mask_original_error(tmp_path, monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        provisioner_api_key="test-key",
        public_sip_uri="sip:asterisk.test:5060;transport=udp",
        livekit_sip_uri="sip:livekit.test:5060;transport=udp",
        ami_username="provisioner",
        ami_password="secret",
        state_file=str(tmp_path / "state.json"),
        generated_pjsip_file=str(tmp_path / "pjsip.conf"),
        generated_dialplan_file=str(tmp_path / "extensions.conf"),
        enable_recording=False,
    )
    service = ProvisioningService(settings)
    service.ami = FailingAmi()
    connection_id = str(uuid.uuid4())
    connection = ConnectionSpec(
        company_id=uuid.uuid4(),
        name="Customer IP trunk",
        provider="generic_sip",
        mode="ip_trunk",
        phone_number="+19714361744",
        allowed_addresses=["203.0.113.10/32"],
        public_sip_uri=settings.public_sip_uri,
    )
    original_render = service._render
    render_count = 0

    def fail_only_during_rollback(connections, extensions):
        nonlocal render_count
        render_count += 1
        if render_count == 2:
            raise PermissionError("rollback write failure")
        original_render(connections, extensions)

    monkeypatch.setattr(service, "_render", fail_only_during_rollback)

    with pytest.raises(RuntimeError, match="original AMI reload failure"):
        await service.upsert(connection_id, connection)


@pytest.mark.asyncio
async def test_extension_upsert_and_delete_share_atomic_state(tmp_path) -> None:
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
    extension_id = str(uuid.uuid4())
    extension = ExtensionSpec(
        company_id=uuid.uuid4(),
        extension="200",
        display_name="Support",
        sip_username="company-a-200",
        sip_password="long-random-password",
    )

    response = await service.upsert_extension(extension_id, extension)

    assert response.resource_id == f"ext-{extension_id}"
    assert "username=company-a-200" in (tmp_path / "pjsip.conf").read_text()
    assert (
        json.loads((tmp_path / "state.json").read_text())["extensions"][extension_id]["extension"]
        == "200"
    )
    assert await service.delete_extension(extension_id) is True
    assert service.ami.reload_count == 2


@pytest.mark.asyncio
async def test_outbound_call_uses_tenant_connection_and_safe_context(tmp_path) -> None:
    config = Settings(
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
    service = ProvisioningService(config)
    service.ami = FakeAmi()
    connection_id = uuid.uuid4()
    company_id = uuid.uuid4()
    await service.upsert(
        str(connection_id),
        ConnectionSpec(
            company_id=company_id,
            name="Outbound registration",
            provider="generic_sip",
            mode="registration",
            phone_number="+19714361744",
            server_uri="provider.test",
            auth_username="customer-1",
            auth_password="provider-secret",
            public_sip_uri=config.public_sip_uri,
        ),
    )
    attempt_id = uuid.uuid4()
    response = await service.originate(
        OutboundCallSpec(
            attempt_id=attempt_id,
            connection_id=connection_id,
            campaign_type="voice_broadcast_keypad",
            destination_number="+14155550100",
            caller_id="+19714361744",
            media_id="a" * 64,
            company_id=company_id,
            campaign_id=uuid.uuid4(),
            recipient_id=uuid.uuid4(),
            call_id=uuid.uuid4(),
            keypad_actions={"1": "opt_out", "2": "extension:100"},
        )
    )

    assert response.accepted is True
    assert service.ami.originate_kwargs["context"] == "ai-agent-outbound-keypad"
    assert service.ami.originate_kwargs["variables"]["AI_KEY_1"] == "opt_out"
    assert service.ami.originate_kwargs["variables"]["AI_KEY_2"].endswith("e100")


@pytest.mark.asyncio
async def test_reconcile_renders_new_contexts_from_persisted_state(tmp_path) -> None:
    config = Settings(
        _env_file=None,
        provisioner_api_key="test-key",
        public_sip_uri="sip:asterisk.test:5060;transport=udp",
        livekit_sip_uri="sip:livekit.test:5060;transport=udp",
        ami_username="provisioner",
        ami_password="secret",
        state_file=str(tmp_path / "state.json"),
        generated_pjsip_file=str(tmp_path / "pjsip.conf"),
        generated_dialplan_file=str(tmp_path / "extensions.conf"),
        enable_recording=False,
    )
    (tmp_path / "state.json").write_text(
        json.dumps({"version": 2, "connections": {}, "extensions": {}})
    )
    service = ProvisioningService(config)
    service.ami = FakeAmi()

    await service.reconcile()

    dialplan = (tmp_path / "extensions.conf").read_text()
    assert "[ai-agent-outbound-ai]" in dialplan
    assert "[ai-agent-outbound-broadcast]" in dialplan
    assert "[ai-agent-outbound-keypad]" in dialplan
    assert service.ami.reload_count == 1
