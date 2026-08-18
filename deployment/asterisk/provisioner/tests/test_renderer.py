import uuid

from app.config import Settings
from app.models import ConnectionSpec, ExtensionSpec
from app.renderer import (
    extension_route,
    provider_server_uri,
    render_dialplan,
    render_pjsip,
)


def settings(**overrides) -> Settings:
    values = {
        "provisioner_api_key": "test-key",
        "public_sip_uri": "sip:asterisk.test:5061;transport=tls",
        "livekit_sip_uri": "sip:livekit.test:5061;transport=tls",
        "ami_username": "provisioner",
        "ami_password": "secret",
    }
    return Settings(_env_file=None, **values, **overrides)


def spec(**overrides) -> ConnectionSpec:
    values = {
        "company_id": uuid.uuid4(),
        "name": "Customer trunk",
        "provider": "generic_sip",
        "mode": "ip_trunk",
        "phone_number": "+19714361744",
        "allowed_addresses": ["203.0.113.10/32"],
        "public_sip_uri": "sip:asterisk.test:5061;transport=tls",
    }
    values.update(overrides)
    return ConnectionSpec(**values)


def test_ip_trunk_generates_identify_and_did_route() -> None:
    connection_id = str(uuid.uuid4())
    connection = spec()

    pjsip = render_pjsip({connection_id: connection}, settings())
    dialplan = render_dialplan({connection_id: connection}, settings(enable_recording=False))

    assert "match=203.0.113.10/32" in pjsip
    assert "exten => +19714361744,1,Gosub(ai-agent-forward" in dialplan
    assert "Dial(PJSIP/${ARG1}@ai-livekit" in dialplan
    assert "Set(__TRANSFER_CONTEXT=ai-agent-transfer-inbound)" in dialplan


def test_registration_generates_provider_registration_and_port() -> None:
    connection_id = str(uuid.uuid4())
    connection = spec(
        mode="registration",
        allowed_addresses=[],
        server_uri="sip:provider.test",
        server_port=5070,
        auth_username="customer-1",
        auth_password="provider-secret",
        transport="tls",
    )

    pjsip = render_pjsip({connection_id: connection}, settings())

    assert "server_uri=sip:provider.test:5070" in pjsip
    assert "transport=0.0.0.0-tls" in pjsip
    assert "line=yes" in pjsip
    assert "password=provider-secret" in pjsip
    assert provider_server_uri("provider.test", 5070) == "sip:provider.test:5070"


def test_employee_extension_has_tenant_scoped_registration_and_transfer_route() -> None:
    extension_id = str(uuid.uuid4())
    company_id = uuid.uuid4()
    extension = ExtensionSpec(
        company_id=company_id,
        extension="100",
        display_name="Sales",
        sip_username="company-a-100",
        sip_password="long-random-password",
        transport="tls",
    )
    extensions = {extension_id: extension}

    pjsip = render_pjsip({}, settings(), extensions)
    dialplan = render_dialplan({}, settings(enable_recording=False), extensions)

    assert "username=company-a-100" in pjsip
    assert "password=long-random-password" in pjsip
    assert pjsip.count("[company-a-100]") == 2
    assert "aors=company-a-100" in pjsip
    assert "identify_by=auth_username,username" in pjsip
    assert f"context=ai-tenant-{company_id.hex}" in pjsip
    assert f"exten => {extension_route(company_id, '100')},1" in dialplan
    assert "exten => 100,1,Dial(PJSIP/company-a-100,30)" in dialplan
    assert "context=ai-agent-transfer-inbound" in pjsip


def test_twilio_requires_admin_managed_source_cidrs() -> None:
    connection_id = str(uuid.uuid4())
    twilio = spec(provider="twilio", mode="twilio", allowed_addresses=[])

    try:
        render_pjsip({connection_id: twilio}, settings())
    except ValueError as exc:
        assert "TWILIO_SIGNALING_CIDRS" in str(exc)
    else:
        raise AssertionError("Twilio without signaling CIDRs must be rejected")


def test_outbound_dialplan_and_twilio_termination_are_rendered() -> None:
    connection_id = str(uuid.uuid4())
    twilio = spec(
        provider="twilio",
        mode="twilio",
        allowed_addresses=[],
        server_uri="sip:mw-test.pstn.twilio.com",
        auth_username="mw-test",
        auth_password="generated-secret",
        transport="tls",
    )
    config = settings(twilio_signaling_cidrs="54.172.60.0/30")

    pjsip = render_pjsip({connection_id: twilio}, config)
    dialplan = render_dialplan({connection_id: twilio}, config)

    assert "contact=sip:mw-test.pstn.twilio.com" in pjsip
    assert "outbound_auth=" in pjsip
    assert "[ai-agent-outbound-ai]" in dialplan
    assert "[ai-agent-outbound-broadcast]" in dialplan
    assert "[ai-agent-outbound-keypad]" in dialplan
    assert "UserEvent(AIOutboundOptOut" in dialplan
