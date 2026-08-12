import uuid

from app.config import Settings
from app.models import ConnectionSpec
from app.renderer import provider_server_uri, render_dialplan, render_pjsip


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


def test_extension_connections_do_not_claim_ambiguous_did_route() -> None:
    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
    first = spec(extension="sales")
    second = spec(extension="support")

    dialplan = render_dialplan(
        {first_id: first, second_id: second}, settings(enable_recording=False)
    )

    assert "exten => sales,1" in dialplan
    assert "exten => support,1" in dialplan
    assert "exten => +19714361744,1" not in dialplan


def test_twilio_requires_admin_managed_source_cidrs() -> None:
    connection_id = str(uuid.uuid4())
    twilio = spec(provider="twilio", mode="twilio", allowed_addresses=[])

    try:
        render_pjsip({connection_id: twilio}, settings())
    except ValueError as exc:
        assert "TWILIO_SIGNALING_CIDRS" in str(exc)
    else:
        raise AssertionError("Twilio without signaling CIDRs must be rejected")
