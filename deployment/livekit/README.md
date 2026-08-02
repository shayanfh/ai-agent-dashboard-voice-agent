# LiveKit SIP setup

Replace placeholders, then create the long-lived infrastructure explicitly:

```bash
lk sip inbound create deployment/livekit/inbound-trunk.example.json
lk sip dispatch create deployment/livekit/dispatch-rule.example.json --trunks SIP_TRUNK_ID
```

The example accepts destination `1000`, matching the tested Backend mapping. If the trunk already
exists, do not create a duplicate. The worker reads `X-Asterisk-LinkedID` directly with the SIP
header RPC, so the existing trunk can remain unchanged. The mapping in the JSON is a fallback for
asynchronous participant attributes. If you choose to add it to an existing trunk, replace the
trunk through the LiveKit SIP API while preserving its ID, numbers, authentication, and allowed
addresses; the CLI field-update operation cannot update every trunk property.

The dispatch `agentName` must remain `ai-agent-dashboard-inbound`, matching
`LIVEKIT_AGENT_NAME`. Each call gets an isolated room with the `call-` prefix.

