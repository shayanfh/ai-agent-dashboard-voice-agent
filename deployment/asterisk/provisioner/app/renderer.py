from urllib.parse import urlparse

from app.config import Settings
from app.models import ConnectionSpec, ExtensionSpec


def section_id(connection_id: str) -> str:
    return f"pc-{connection_id.replace('-', '')}"


def extension_section_id(extension_id: str) -> str:
    return f"ext-{extension_id.replace('-', '')}"


def extension_route(company_id: object, extension: str) -> str:
    company_hex = str(company_id).replace("-", "")
    return f"x{company_hex}e{extension}"


def tenant_context(company_id: object) -> str:
    return f"ai-tenant-{str(company_id).replace('-', '')}"


def sip_host(uri: str) -> str:
    parsed = urlparse(uri if "://" in uri else f"sip://{uri.removeprefix('sip:')}")
    return parsed.hostname or uri.removeprefix("sip:").split(";", 1)[0].split(":", 1)[0]


def destination_uri(public_uri: str, phone_number: str) -> str:
    value = public_uri.removeprefix("sip:")
    host, separator, parameters = value.partition(";")
    suffix = f";{parameters}" if separator else ""
    return f"sip:{phone_number}@{host}{suffix}"


def provider_server_uri(server: str, port: int | None) -> str:
    value = server if server.startswith("sip:") else f"sip:{server}"
    base, separator, parameters = value.partition(";")
    parsed = urlparse(f"//{base.removeprefix('sip:')}")
    if port and parsed.port is None:
        base = f"{base}:{port}"
    suffix = f";{parameters}" if separator else ""
    return f"{base}{suffix}"


def _render_livekit(settings: Settings) -> list[str]:
    host = sip_host(settings.livekit_sip_uri)
    lines = [
        "; Managed by asterisk-provisioner. Do not edit.",
        "[ai-livekit-aor]",
        "type=aor",
        f"contact={settings.livekit_sip_uri}",
        "qualify_frequency=30",
        "",
    ]
    if settings.livekit_auth_username and settings.livekit_auth_password:
        lines.extend(
            [
                "[ai-livekit-auth]",
                "type=auth",
                "auth_type=userpass",
                f"username={settings.livekit_auth_username}",
                f"password={settings.livekit_auth_password}",
                "",
            ]
        )
    lines.extend(
        [
            "[ai-livekit]",
            "type=endpoint",
            "context=ai-agent-transfer-inbound",
            "allow_transfer=yes",
            f"transport={settings.livekit_transport_name}",
            "aors=ai-livekit-aor",
            "outbound_auth=ai-livekit-auth" if settings.livekit_auth_username else "",
            f"from_domain={host}",
            "disallow=all",
            "allow=ulaw,alaw",
            "direct_media=no",
            "rtp_symmetric=yes",
            "force_rport=yes",
            "rewrite_contact=yes",
            "",
        ]
    )
    return [line for line in lines if line != ""] + [""]


def render_pjsip(
    connections: dict[str, ConnectionSpec],
    settings: Settings,
    extensions: dict[str, ExtensionSpec] | None = None,
) -> str:
    lines = _render_livekit(settings)
    if any(spec.mode == "twilio" for spec in connections.values()):
        if not settings.twilio_cidrs:
            raise ValueError("TWILIO_SIGNALING_CIDRS is required for Twilio connections")
        lines.extend(
            [
                "[ai-twilio-inbound]",
                "type=endpoint",
                "context=ai-agent-provider-inbound",
                "disallow=all",
                "allow=ulaw,alaw",
                "direct_media=no",
                "rtp_symmetric=yes",
                "force_rport=yes",
                "rewrite_contact=yes",
                "",
                "[ai-twilio-identify]",
                "type=identify",
                "endpoint=ai-twilio-inbound",
                *(f"match={cidr}" for cidr in settings.twilio_cidrs),
                "",
            ]
        )

    for connection_id, spec in sorted(connections.items()):
        sid = section_id(connection_id)
        if spec.mode == "twilio":
            continue
        if spec.mode == "ip_trunk":
            lines.extend(
                [
                    f"[{sid}]",
                    "type=endpoint",
                    "context=ai-agent-provider-inbound",
                    "disallow=all",
                    "allow=ulaw,alaw",
                    "direct_media=no",
                    "rtp_symmetric=yes",
                    "force_rport=yes",
                    "rewrite_contact=yes",
                    "",
                    f"[{sid}-identify]",
                    "type=identify",
                    f"endpoint={sid}",
                    *(f"match={address}" for address in spec.allowed_addresses),
                    "",
                ]
            )
            continue

        server_uri = provider_server_uri(spec.server_uri or "", spec.server_port)
        realm = spec.realm or "*"
        lines.extend(
            [
                f"[{sid}-auth]",
                "type=auth",
                "auth_type=userpass",
                f"username={spec.auth_username}",
                f"password={spec.auth_password}",
                f"realm={realm}",
                "",
                f"[{sid}-aor]",
                "type=aor",
                f"contact={server_uri}",
                "qualify_frequency=30",
                "",
                f"[{sid}]",
                "type=endpoint",
                "context=ai-agent-provider-inbound",
                f"transport={settings.transport_name(spec.transport)}",
                f"aors={sid}-aor",
                f"outbound_auth={sid}-auth",
                "disallow=all",
                "allow=ulaw,alaw",
                "direct_media=no",
                "rtp_symmetric=yes",
                "force_rport=yes",
                "rewrite_contact=yes",
                "",
                f"[{sid}-registration]",
                "type=registration",
                f"transport={settings.transport_name(spec.transport)}",
                f"outbound_auth={sid}-auth",
                f"server_uri={server_uri}",
                f"client_uri=sip:{spec.auth_username}@{sip_host(server_uri)}",
                f"contact_user={spec.phone_number}",
                f"endpoint={sid}",
                "line=yes",
                "retry_interval=60",
                "forbidden_retry_interval=300",
                "expiration=3600",
                f"outbound_proxy={spec.outbound_proxy}" if spec.outbound_proxy else "",
                "",
            ]
        )
    for extension_id, spec in sorted((extensions or {}).items()):
        if not spec.enabled:
            continue
        sid = extension_section_id(extension_id)
        endpoint_id = spec.sip_username
        lines.extend(
            [
                f"[{sid}-auth]",
                "type=auth",
                "auth_type=userpass",
                f"username={spec.sip_username}",
                f"password={spec.sip_password}",
                "",
                # Inbound REGISTER matches its To/Auth username against the
                # AoR/endpoint object ID, not the auth object's username.
                f"[{endpoint_id}]",
                "type=aor",
                "max_contacts=1",
                "remove_existing=yes",
                "qualify_frequency=30",
                "",
                f"[{endpoint_id}]",
                "type=endpoint",
                f"transport={settings.transport_name(spec.transport)}",
                f"context={tenant_context(spec.company_id)}",
                f"auth={sid}-auth",
                f"aors={endpoint_id}",
                "identify_by=auth_username,username",
                f"callerid={spec.extension}",
                "disallow=all",
                "allow=ulaw,alaw",
                "direct_media=no",
                "rtp_symmetric=yes",
                "force_rport=yes",
                "rewrite_contact=yes",
                "dtmf_mode=rfc4733",
                "",
            ]
        )
    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def render_dialplan(
    connections: dict[str, ConnectionSpec],
    settings: Settings,
    extensions: dict[str, ExtensionSpec] | None = None,
) -> str:
    lines = [
        "; Managed by asterisk-provisioner. Do not edit.",
        "[ai-agent-provider-inbound]",
    ]
    seen: set[str] = set()
    for connection_id, spec in sorted(connections.items()):
        destinations = [spec.phone_number, spec.phone_number.removeprefix("+")]
        if spec.mode == "registration" and spec.auth_username:
            destinations.append(spec.auth_username)
        for destination in destinations:
            if destination in seen:
                continue
            seen.add(destination)
            lines.extend(
                [
                    f"exten => {destination},1,Gosub(ai-agent-forward,s,1("
                    f"{spec.phone_number},{connection_id}))",
                    " same => n,Hangup()",
                ]
            )
    lines.extend(
        [
            "",
            "[ai-agent-forward]",
            "exten => s,1,NoOp(Forwarding ${ARG1} connection ${ARG2} to LiveKit)",
        ]
    )
    if settings.enable_recording:
        lines.extend(
            [
                " same => n,Set(__AST_RECORDING_ID=${FILTER(0-9A-Za-z_.-,${CHANNEL(linkedid)})})",
                f" same => n,Set(AST_RECORDING_FILE={settings.recording_directory}/"
                "${AST_RECORDING_ID}.wav)",
                " same => n,MixMonitor(${AST_RECORDING_FILE},b,i(AST_MIXMONITOR_ID),"
                f"{settings.recording_uploader} ${{AST_RECORDING_FILE}} "
                "${AST_RECORDING_ID})",
            ]
        )
    lines.append(
        " same => n,Dial(PJSIP/${ARG1}@ai-livekit,60,b(ai-agent-add-headers^s^1("
        "${ARG1},${ARG2},${CHANNEL(linkedid)},${ARG3})))"
    )
    if settings.enable_recording:
        lines.append(" same => n,StopMixMonitor(${AST_MIXMONITOR_ID})")
    lines.extend(
        [
            " same => n,Return()",
            "",
            "[ai-agent-add-headers]",
            "exten => s,1,Set(PJSIP_HEADER(add,X-Asterisk-LinkedID)=${ARG3})",
            ' same => n,ExecIf($["${ARG4}" != ""]?Set(PJSIP_HEADER(add,'
            "X-Destination-Extension)=${ARG4}))",
            " same => n,Set(PJSIP_HEADER(add,X-Phone-Connection-ID)=${ARG2})",
            " same => n,Return()",
        ]
    )
    active_extensions = {
        key: value for key, value in (extensions or {}).items() if value.enabled
    }
    lines.extend(["", "[ai-agent-transfer-inbound]"])
    for _extension_id, spec in sorted(active_extensions.items()):
        route = extension_route(spec.company_id, spec.extension)
        lines.extend(
            [
                f"exten => {route},1,NoOp(AI transfer to extension {spec.extension})",
                f" same => n,Dial(PJSIP/{spec.sip_username},30)",
                " same => n,Hangup()",
            ]
        )

    companies = sorted({str(spec.company_id) for spec in active_extensions.values()})
    for company_id in companies:
        lines.extend(["", f"[{tenant_context(company_id)}]"])
        for _extension_id, spec in sorted(active_extensions.items()):
            if str(spec.company_id) != company_id:
                continue
            lines.extend(
                [
                    f"exten => {spec.extension},1,Dial(PJSIP/{spec.sip_username},30)",
                    " same => n,Hangup()",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"
