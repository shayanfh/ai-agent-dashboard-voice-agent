# LiveKit SIP setup

Replace placeholders, then create the long-lived infrastructure explicitly:

```bash
lk sip inbound create deployment/livekit/inbound-trunk.example.json
lk sip dispatch create deployment/livekit/dispatch-rule.example.json --trunks SIP_TRUNK_ID
```

The dispatch `agentName` must remain `ai-agent-dashboard-inbound`, matching
`LIVEKIT_AGENT_NAME`. Each call gets an isolated room with the `call-` prefix.

