# LiveKit SIP setup

Create this infrastructure once for the central Asterisk gateway. Customer provisioning must not
create a LiveKit trunk per phone number. Replace the Asterisk address, then run:

```bash
lk sip inbound create deployment/livekit/inbound-trunk.example.json
lk sip dispatch create deployment/livekit/dispatch-rule.example.json --trunks SIP_TRUNK_ID
```

The empty `numbers` list lets this one trunk receive every DID that Asterisk forwards; access is
restricted by `allowedAddresses`. If the trunk already exists, update it instead of creating a
duplicate. Header mappings preserve Asterisk correlation, optional destination extension, and the
Backend connection ID. The worker also reads the headers through the SIP header RPC.

LiveKit Cloud requires `allowedAddresses` to be enabled for the project. If it is unavailable,
configure `authUsername` and `authPassword` on both this trunk and the Asterisk LiveKit endpoint
instead; never leave an all-number trunk without address or digest authentication.

The dispatch `agentName` must remain `ai-agent-dashboard-inbound`, matching
`LIVEKIT_AGENT_NAME`. Each call gets an isolated room with the `call-` prefix.

