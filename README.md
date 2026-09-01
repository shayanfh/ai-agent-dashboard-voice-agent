# AI Agent Dashboard Voice Agent

Production-style runtime connecting customer SIP/Twilio calls through the central FreePBX
gateway and LiveKit SIP to the existing
Dashboard Backend. One explicitly named, concurrent worker (`ai-agent-dashboard-inbound`) loads
each tenant's agent configuration by called number; no customer configuration is
stored globally and the service never accesses PostgreSQL directly.

## Call flow

Inbound: Caller → provider → central FreePBX → LiveKit SIP → isolated room → this worker.

Outbound AI: Backend/Celery → FreePBX AMI → provider → recipient → LiveKit SIP → this worker.

Browser test: Dashboard browser → LiveKit WebRTC room → this worker. This path does not use
FreePBX, SIP, or a customer phone number.

Voice Broadcast: Backend/Celery → FreePBX AMI → provider → recipient → cached WAV playback. The
broadcast-only path does not create a LiveKit room or consume Voice Agent/LLM resources.

The worker extracts `sip.phoneNumber`, `sip.trunkPhoneNumber`, and call/trunk IDs from
the SIP participant. When Asterisk recording is enabled it also extracts the forwarded
`X-Asterisk-LinkedID`. It resolves the agent, creates the call, builds tenant-scoped STT/LLM/TTS
objects, greets immediately, persists committed conversation items, and completes the call.

### Hybrid Realtime agents

When `use_realtime=true`, caller audio is sent directly to the fixed OpenAI `gpt-realtime` model,
configured with `modalities=["text"]`. The returned text is streamed through ElevenLabs TTS using
the customer's selected `voice_id`. The customer cannot select the Realtime or TTS model; these
are server-owned settings. Pipeline agents continue to use separate STT, LLM, and TTS providers.

The default Realtime TTS model is `eleven_flash_v2_5`, selected for low conversational latency.
Set both provider credentials on the Voice Agent server:

```dotenv
OPENAI_API_KEY=...
ELEVENLABS_API_KEY=...
REALTIME_MODEL=gpt-realtime
REALTIME_INPUT_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
REALTIME_TTS_MODEL=eleven_flash_v2_5
REALTIME_TTS_VOICE=JBFqnCBsd6RMkjVDRZzb
```

`REALTIME_TTS_VOICE` is the fallback only. For each Realtime agent, the Dashboard's `voice_id`
field should contain an ElevenLabs voice ID copied from that account's Voice Library. Restart the
Voice Agent after changing server-owned model settings or credentials.

### Browser test calls

The Backend creates a tenant-scoped Call and returns a short-lived LiveKit room token containing
an explicit dispatch for this worker. Dispatch metadata contains the verified Call, Company,
Agent, and browser participant identities. The worker resolves that existing Call through
`resolve-agent-by-id`, loads the same Agent configuration and cached Knowledge Base as a real call,
and persists transcript, summary, outcome, extracted data, and duration normally.

Test mode never exposes `transfer_to_extension` to the LLM and uses test-specific instructions
when a tester asks to transfer. It also enforces a hard session timeout independently of the
frontend countdown:

```dotenv
WEB_TEST_CALL_MAX_DURATION_SECONDS=600
```

Keep this value equal to the Backend's `WEB_TEST_CALL_MAX_DURATION_SECONDS`. The Backend caps the
persisted test duration to the same value as a second enforcement layer. The token permits the
browser participant to publish only microphone audio and subscribe to the Agent audio.

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

- `GET /api/v1/internal/voice/resolve-agent?phone_number=...`
- `GET /api/v1/internal/voice/resolve-agent-by-id?agent_id=...&company_id=...&call_id=...`
- `GET /api/v1/internal/voice/knowledge-snapshot?agent_id=...`
- `POST /api/v1/internal/voice/calls`
- `POST /api/v1/internal/voice/calls/{call_id}/transfer-target`
- `POST /api/v1/internal/voice/calls/{call_id}/messages`
- `POST /api/v1/internal/voice/calls/{call_id}/complete`
- `PATCH /api/v1/internal/voice/calls/{call_id}/recording`

Asterisk uploads completed WAV files directly to
`POST /api/v1/internal/voice/recordings/asterisk`; the Voice Agent never proxies recording audio.

The transfer-target endpoint accepts a numeric extension or exact display name (case-insensitive)
and resolves it using the Call's company. Employee names are not accepted. The returned tenant
route is passed to LiveKit `TransferSIPParticipant`; callers cannot choose an arbitrary phone number
or SIP address. Other business operations still require secure backend endpoints before agent tools
are enabled for them.

For an outbound AI leg, the worker synchronously reads Asterisk's `X-Company-ID`, `X-Agent-ID`,
`X-Campaign-ID`, `X-Recipient-ID`, and `X-Call-ID` headers. The Backend verifies that the existing
Call, Agent, and Company belong to the same tenant before returning agent configuration. The worker
reuses the Call created by the campaign dispatcher instead of creating a duplicate. Recipient
fields and the campaign objective are added as untrusted outbound context, and the opening turn
identifies the company, discloses the AI assistant, and states the purpose of the call.

## Knowledge Base latency and synchronization

`resolve-agent` returns the company's monotonic `knowledge_version`. The worker caches a local
snapshot under `(agent_id, knowledge_version)`. Calls using an already cached version perform no
additional Knowledge Base download; the first call after a change downloads one snapshot while
the normal Call creation request runs in parallel. Concurrent calls for the same new version share
one in-flight snapshot request.

For each completed caller turn, `KnowledgeAgent.on_user_turn_completed` runs a local multilingual
BM25-style token search plus fuzzy title matching and injects only the best matching context before
LLM generation. There is no HTTP request, remote vector search, embedding API request, or LLM tool
round trip per question. Q&A and extracted document text are treated as untrusted factual data and
cannot override platform instructions.

```dotenv
KNOWLEDGE_CACHE_MAX_ENTRIES=128
KNOWLEDGE_RETRIEVAL_TOP_K=4
KNOWLEDGE_RETRIEVAL_MAX_CHARS=6000
```

## SIP provisioning

See `deployment/livekit` for the one central inbound trunk and dispatch rule, and
`deployment/asterisk` for the Asterisk provisioner. Customer trunks are provisioned through the
Backend, never during worker startup. The dispatch rule and worker must use the same agent name.

## Asterisk recording

Recording is performed by Asterisk `MixMonitor`, not by the Voice Agent container. This keeps the
recording at the telephony edge and avoids running LiveKit Egress. The correlation path is:

`Asterisk linkedid -> X-Asterisk-LinkedID -> LiveKit participant attribute -> Call metadata -> WAV upload`

To enable correlation, set `ENABLE_CALL_RECORDING=true` on the Voice Agent and install the
uploader and dialplan snippets from `deployment/asterisk`. The `headersToAttributes` mapping in
`deployment/livekit/inbound-trunk.example.json` is a recommended fallback, not a requirement for
the direct RPC path. A missing linked ID is logged as `asterisk_linked_id_missing`; the call still
proceeds, but its recording cannot be attached automatically.

The worker first reads the linked ID directly with LiveKit's `lk.sip.GetRemoteHeaders` RPC and
uses the mapped participant attribute as a fallback. This avoids depending on the timing of
asynchronous SIP attribute updates.

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
7. Twilio, the SIP provider, or Asterisk routes a test call to LiveKit SIP.
8. The call creates a `call-...` room and the SIP participant joins.
9. The greeting plays once.
10. Caller/assistant messages appear in the Dashboard.
11. Disconnecting stores duration, summary and outcome.
12. Asterisk uploads WAV and the Call receives a recording URL.
13. Asking for an active employee extension transfers the SIP caller back to FreePBX.

Recording correlation is disabled by default. Set `ENABLE_CALL_RECORDING=true` only after the
LiveKit header mapping and Asterisk uploader are installed.
For failures, inspect JSON logs by correlation ID, then verify SIP participant attributes and the
called number format matches the backend mapping exactly.

### Post-call AI analysis

When a call ends, the worker sends the committed transcript to a fixed OpenAI model once and
stores a structured result containing a one-sentence summary, the final outcome, and explicitly
stated customer/request data. The analyzer is independent of the LLM configured for each tenant
agent. Valid outcomes are `booking_created`, `information_request`, `callback_requested`,
`no_action`, and `failed`. Confirmed bookings and callback requests also create the corresponding
Dashboard Request through the existing Backend completion flow.

```dotenv
SUMMARY_LLM_MODEL=gpt-5.6-luna
SUMMARY_LLM_TIMEOUT_SECONDS=20
SUMMARY_MAX_TRANSCRIPT_CHARS=30000
SUMMARY_MAX_OUTPUT_TOKENS=400
```

The response uses strict JSON Schema and transcript content is sent with `store=false`. If analysis
times out, returns invalid data, or fails, call completion still succeeds with a caller-only
fallback summary and `outcome=no_action`.

### Agent hangup

The agent has LiveKit's `EndCallTool`. When the caller clearly says goodbye or indicates that the
conversation is finished, the tool plays a brief goodbye, closes the session, and deletes the
room so the SIP caller is disconnected. It is hidden during the initial greeting and must not be
used for silence, unclear speech, hold, transfer, or temporary hesitation. Agent-initiated calls
are completed with `completion_reason=agent_hangup` before post-call analysis is persisted.

### Employee extension transfer

The `transfer_to_extension` tool confirms the requested internal number or display name, asks the
Backend for a tenant-scoped target, and uses LiveKit SIP REFER to return the caller to FreePBX.
FreePBX then rings the registered employee endpoint. A successful transfer is stored on the Call
using the resolved extension number; an unavailable, ambiguous, or cross-tenant destination is
rejected and the AI continues the conversation.
