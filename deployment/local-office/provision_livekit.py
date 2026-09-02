"""Create the single local Asterisk-to-LiveKit trunk and dispatch rule."""

import asyncio
import json
import os

from livekit import api

TRUNK_NAME = "Mozaic local Asterisk"
RULE_NAME = "Mozaic local inbound calls"


async def main() -> None:
    server_ip = os.environ["SERVER_IP"]
    client = api.LiveKitAPI(
        os.environ["LIVEKIT_URL"],
        os.environ["LIVEKIT_API_KEY"],
        os.environ["LIVEKIT_API_SECRET"],
    )
    try:
        trunks = await client.sip.list_sip_inbound_trunk(
            api.ListSIPInboundTrunkRequest()
        )
        trunk = next((item for item in trunks.items if item.name == TRUNK_NAME), None)
        if trunk is None:
            trunk = await client.sip.create_sip_inbound_trunk(
                api.CreateSIPInboundTrunkRequest(
                    trunk=api.SIPInboundTrunkInfo(
                        name=TRUNK_NAME,
                        numbers=[],
                        allowed_addresses=[f"{server_ip}/32"],
                        headers_to_attributes={
                            "X-Asterisk-LinkedID": "asterisk.linkedID",
                            "X-Destination-Extension": "sip.extension",
                            "X-Phone-Connection-ID": "asterisk.connectionID",
                        },
                        metadata=json.dumps({"deployment": "mozaic-local-office"}),
                    )
                )
            )
            print(f"Created LiveKit SIP trunk {trunk.sip_trunk_id}")
        else:
            print(f"Using existing LiveKit SIP trunk {trunk.sip_trunk_id}")

        rules = await client.sip.list_sip_dispatch_rule(
            api.ListSIPDispatchRuleRequest()
        )
        rule = next((item for item in rules.items if item.name == RULE_NAME), None)
        if rule is None:
            rule = await client.sip.create_sip_dispatch_rule(
                api.CreateSIPDispatchRuleRequest(
                    rule=api.SIPDispatchRule(
                        dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                            room_prefix="call-"
                        )
                    ),
                    trunk_ids=[trunk.sip_trunk_id],
                    name=RULE_NAME,
                    metadata=json.dumps({"deployment": "mozaic-local-office"}),
                    room_config=api.RoomConfiguration(
                        agents=[
                            api.RoomAgentDispatch(
                                agent_name="ai-agent-dashboard-inbound",
                                metadata=json.dumps({"source": "asterisk"}),
                            )
                        ]
                    ),
                )
            )
            print(f"Created LiveKit dispatch rule {rule.sip_dispatch_rule_id}")
        else:
            print(f"Using existing LiveKit dispatch rule {rule.sip_dispatch_rule_id}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
