# AI Agent Dashboard Voice Agent

Production-style MVP runtime connecting inbound Asterisk calls, LiveKit SIP, and the existing
Dashboard Backend. One explicitly named, concurrent worker (`ai-agent-dashboard-inbound`) loads
each tenant's agent configuration by called number or extension; no customer configuration is
stored globally and the service never accesses PostgreSQL directly.

## Call flow

Caller → gateway/provider → Asterisk/FreePBX → LiveKit SIP → isolated LiveKit room → this worker
→ Dashboard Backend internal API.

The worker extracts `sip.phoneNumber`, `sip.trunkPhoneNumber`, call/trunk IDs and extension from
the SIP participant. It resolves the agent, creates the call, builds tenant-scoped STT/LLM/TTS
objects, greets immediately, persists committed conversation items, and completes the call.

## Setup

Python 3.12 and a LiveKit deployment with SIP are required.

```bash
cp .env.example .env
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
python -m app.main dev
```

For production run `python -m app.main start`, or `docker compose up --build`. The Backend,
LiveKit, and Voice Agent may run on separate servers. Set `DASHBOARD_BACKEND_URL` to the
reachable HTTPS address of the Backend, for example `https://dashboard-api.example.com`, and
set `LIVEKIT_URL` to the remote LiveKit WebSocket URL. No shared Docker network is required.
`DASHBOARD_INTERNAL_API_KEY` must equal the Backend `INTERNAL_API_KEY`. Provider keys stay only
in this service.

The Voice Agent server needs outbound access to the Dashboard Backend, LiveKit, and configured
AI providers. The Backend firewall or reverse proxy must allow the Voice Agent server to reach
the internal voice API. Prefer a private network, VPN, or IP allowlist in addition to HTTPS and
the internal API key.

## Backend contract currently used

- `GET /api/v1/internal/voice/resolve-agent?phone_number=...&extension=...`
- `POST /api/v1/internal/voice/calls`
- `POST /api/v1/internal/voice/calls/{call_id}/messages`
- `POST /api/v1/internal/voice/calls/{call_id}/complete`

The current Dashboard Backend does not yet expose secure internal endpoints for knowledge search,
request creation, business information, usage reporting, or status updates. The runtime therefore
does not expose tools that could falsely claim those operations succeeded. Add those endpoints to
the backend contract before enabling those tools.

## SIP provisioning

See `deployment/livekit` for inbound trunk and individual dispatch examples, and
`deployment/asterisk` for PJSIP/dialplan examples. Infrastructure is never provisioned during
worker startup. The dispatch rule and worker must use the exact same agent name.

## Verification

```bash
pytest
ruff check .
python scripts/test_backend_connection.py
```

End-to-end checklist:

1. Backend runs and its internal key matches.
2. An enabled phone-number mapping and assigned agent exist.
3. LiveKit and LiveKit SIP are reachable.
4. The inbound trunk and individual dispatch rule exist.
5. Dispatch uses `ai-agent-dashboard-inbound`.
6. The worker appears available in LiveKit.
7. Asterisk routes a test call to LiveKit SIP.
8. The call creates a `call-...` room and the SIP participant joins.
9. The greeting plays once.
10. Caller/assistant messages appear in the Dashboard.
11. Disconnecting stores duration, summary and outcome.

Recording is intentionally disabled by default; no-op recording is not presented as operational.
For failures, inspect JSON logs by correlation ID, then verify SIP participant attributes and the
called number format matches the backend mapping exactly.
