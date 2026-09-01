import asyncio
import json
from dataclasses import replace
from typing import cast
from uuid import uuid4

import structlog
from livekit import agents, rtc
from livekit.agents import AgentSession, function_tool, llm, room_io
from livekit.agents.beta import EndCallTool

from app.agent.context import CallContext
from app.agent.instructions import compose_instructions
from app.agent.knowledge_agent import KnowledgeAgent
from app.backend.client import DashboardBackendClient
from app.backend.schemas import CallCreate, KnowledgeSnapshot
from app.core.config import Settings
from app.core.exceptions import CallerNotFoundError
from app.providers.factories import (
    create_llm,
    create_realtime_llm,
    create_realtime_tts,
    create_stt,
    create_tts,
    create_vad,
)
from app.services.call_service import CallLifecycleService
from app.services.knowledge_service import KnowledgeIndex, knowledge_cache
from app.services.summary_service import OpenAICallAnalyzer
from app.services.transcript_service import TranscriptService
from app.telephony.attributes import (
    SipCallInfo,
    extract_sip_call_info,
    parse_metadata,
    parse_remote_sip_headers,
)

logger = structlog.get_logger()


async def wait_for_sip_participant(
    ctx: agents.JobContext, wait_seconds: float
) -> rtc.RemoteParticipant:
    try:
        participant = await asyncio.wait_for(
            agents.utils.wait_for_participant(
                ctx.room, kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP
            ),
            timeout=wait_seconds,
        )
    except TimeoutError as exc:
        raise CallerNotFoundError("SIP caller did not join before timeout") from exc
    if not isinstance(participant, rtc.RemoteParticipant):
        raise CallerNotFoundError("Matched participant is not remote")
    return participant


async def wait_for_web_participant(
    ctx: agents.JobContext, participant_identity: str, wait_seconds: float
) -> rtc.RemoteParticipant:
    try:
        participant = await asyncio.wait_for(
            agents.utils.wait_for_participant(ctx.room, identity=participant_identity),
            timeout=wait_seconds,
        )
    except TimeoutError as exc:
        raise CallerNotFoundError("Browser test participant did not join before timeout") from exc
    if not isinstance(participant, rtc.RemoteParticipant):
        raise CallerNotFoundError("Matched browser participant is not remote")
    return participant


async def run_inbound_call(ctx: agents.JobContext, settings: Settings) -> None:
    correlation_id = str(uuid4())
    job_metadata = parse_metadata(ctx.job.metadata)
    web_test = job_metadata.get("call_type") == "web_test"
    await ctx.connect()
    if web_test:
        participant_identity = str(job_metadata.get("participant_identity") or "")
        if not participant_identity:
            raise CallerNotFoundError("Browser test participant identity is missing")
        participant = await wait_for_web_participant(
            ctx, participant_identity, settings.caller_wait_timeout_seconds
        )
        sip = SipCallInfo(
            caller_number=None,
            called_number=None,
            sip_trunk_id=None,
            sip_call_id=None,
            sip_call_id_full=None,
            sip_rule_id=None,
            participant_identity=participant.identity,
            participant_name=participant.name,
            destination_extension=None,
            asterisk_linked_id=None,
            room_name=ctx.room.name,
            dispatch_metadata=job_metadata,
        )
    else:
        participant = await wait_for_sip_participant(ctx, settings.caller_wait_timeout_seconds)
        sip = extract_sip_call_info(
            participant, room_name=ctx.room.name, job_metadata=ctx.job.metadata
        )
    # Outbound routing data arrives as signed/internal X-* SIP headers and must
    # be read synchronously; trunk attribute mappings are updated asynchronously.
    if not web_test and isinstance(participant, rtc.RemoteParticipant):
        try:
            response = await asyncio.wait_for(
                ctx.room.local_participant.perform_rpc(
                    destination_identity=participant.identity,
                    method="lk.sip.GetRemoteHeaders",
                    payload=json.dumps(
                        {
                            "include": [
                                "X-Asterisk-LinkedID",
                                "X-Destination-Extension",
                                "X-Outbound-Call",
                                "X-Company-ID",
                                "X-Agent-ID",
                                "X-Campaign-ID",
                                "X-Recipient-ID",
                                "X-Attempt-ID",
                                "X-Call-ID",
                                "X-Destination-Number",
                            ]
                        }
                    ),
                ),
                timeout=settings.asterisk_linked_id_wait_seconds,
            )
            headers = parse_remote_sip_headers(response)
            sip = replace(
                sip,
                asterisk_linked_id=headers.get("x-asterisk-linkedid"),
                destination_extension=sip.destination_extension
                or headers.get("x-destination-extension"),
                outbound=headers.get("x-outbound-call", "").lower() == "true",
                outbound_company_id=headers.get("x-company-id"),
                outbound_agent_id=headers.get("x-agent-id"),
                outbound_campaign_id=headers.get("x-campaign-id"),
                outbound_recipient_id=headers.get("x-recipient-id"),
                outbound_attempt_id=headers.get("x-attempt-id"),
                outbound_call_id=headers.get("x-call-id"),
                destination_number=headers.get("x-destination-number"),
            )
        except (TimeoutError, ValueError, rtc.RpcError) as exc:
            logger.warning("sip_header_rpc_failed", error=str(exc))

        if settings.enable_call_recording and not sip.asterisk_linked_id:
            sip = extract_sip_call_info(
                participant, room_name=ctx.room.name, job_metadata=ctx.job.metadata
            )
        if not sip.asterisk_linked_id:
            logger.warning(
                "asterisk_linked_id_missing",
                room_name=sip.room_name,
                wait_seconds=settings.asterisk_linked_id_wait_seconds,
            )
    logger.info(
        "sip_routing_resolved",
        room_name=sip.room_name,
        caller_number=sip.caller_number,
        called_number=sip.called_number,
        destination_extension=sip.destination_extension,
        asterisk_linked_id=sip.asterisk_linked_id,
        sip_trunk_id=sip.sip_trunk_id,
        participant_identity=sip.participant_identity,
    )
    if not web_test and not sip.routing_number and not sip.outbound:
        raise CallerNotFoundError("Called number/extension is missing from SIP attributes")

    async with DashboardBackendClient(settings) as backend:
        if web_test:
            required = ("call_id", "company_id", "agent_id")
            if not all(job_metadata.get(key) for key in required):
                raise CallerNotFoundError("Browser test routing metadata is incomplete")
            config = await backend.resolve_agent_by_id(
                agent_id=str(job_metadata["agent_id"]),
                company_id=str(job_metadata["company_id"]),
                call_id=str(job_metadata["call_id"]),
                correlation_id=correlation_id,
            )
        elif sip.outbound:
            if not all((sip.outbound_company_id, sip.outbound_agent_id, sip.outbound_call_id)):
                raise CallerNotFoundError("Outbound routing headers are incomplete")
            config = await backend.resolve_agent_by_id(
                agent_id=cast(str, sip.outbound_agent_id),
                company_id=cast(str, sip.outbound_company_id),
                call_id=cast(str, sip.outbound_call_id),
                correlation_id=correlation_id,
            )
        else:
            config = await backend.resolve_agent(
                phone_number=cast(str, sip.called_number or sip.routing_number),
                correlation_id=correlation_id,
            )
        knowledge_task = asyncio.create_task(
            knowledge_cache.get(
                agent_id=config.agent_id,
                version=config.knowledge_version,
                max_entries=settings.knowledge_cache_max_entries,
                loader=lambda: backend.get_knowledge_snapshot(
                    agent_id=config.agent_id,
                    correlation_id=correlation_id,
                ),
            )
        )
        if web_test:
            call_id = str(job_metadata["call_id"])
            created_company_id = config.company_id
        elif sip.outbound:
            call_id = cast(str, sip.outbound_call_id)
            created_company_id = config.company_id
        else:
            created = await backend.create_call(
                CallCreate(
                    phone_number=sip.called_number or sip.routing_number,
                    caller_number=sip.caller_number,
                    livekit_room_name=sip.room_name,
                    metadata={
                        "asterisk_linked_id": sip.asterisk_linked_id,
                        "sip_call_id": sip.sip_call_id,
                        "sip_call_id_full": sip.sip_call_id_full,
                        "sip_trunk_id": sip.sip_trunk_id,
                        "sip_rule_id": sip.sip_rule_id,
                        "participant_identity": sip.participant_identity,
                    },
                ),
                correlation_id=correlation_id,
                idempotency_key=f"call:{sip.sip_call_id or sip.room_name}",
            )
            call_id = created.call_id
            created_company_id = created.company_id
        try:
            knowledge = await knowledge_task
        except Exception as exc:
            logger.warning(
                "knowledge_snapshot_unavailable",
                agent_id=config.agent_id,
                version=config.knowledge_version,
                error_type=type(exc).__name__,
            )
            knowledge = KnowledgeIndex(
                KnowledgeSnapshot(
                    company_id=config.company_id,
                    agent_id=config.agent_id,
                    version=config.knowledge_version,
                )
            )
        call_context = CallContext(
            call_id=call_id,
            correlation_id=correlation_id,
            company_id=created_company_id,
            agent_id=config.agent_id,
            sip=sip,
            agent_configuration=config,
        )
        log = logger.bind(
            call_id=call_id,
            company_id=config.company_id,
            agent_id=config.agent_id,
            room_name=sip.room_name,
            participant_identity=sip.participant_identity,
            correlation_id=correlation_id,
        )
        hangup_requested = False

        async def on_end_call_tool_called(_: llm.Toolset.ToolCalledEvent) -> None:
            nonlocal hangup_requested
            hangup_requested = True
            log.info("agent_hangup_requested")

        end_call_tool = EndCallTool(
            delete_room=True,
            ignore_on_enter=True,
            end_instructions=(
                "Briefly say goodbye in the current conversation language. "
                "Do not ask another question or continue the conversation."
            ),
            on_tool_called=on_end_call_tool_called,
        )

        @function_tool()
        async def transfer_to_extension(target: str) -> str:
            """Transfer the caller to an active extension after confirmation.

            Args:
                target: The numeric extension or display name explicitly requested by the caller.
            """
            requested_target = target
            try:
                resolved_target = await backend.resolve_transfer_target(
                    call_context.call_id,
                    requested_target,
                    correlation_id=call_context.correlation_id,
                )
                await ctx.transfer_sip_participant(
                    participant,
                    resolved_target.sip_uri,
                    play_dialtone=True,
                )
            except Exception as exc:
                log.warning(
                    "call_transfer_failed",
                    requested_target=requested_target,
                    error_type=type(exc).__name__,
                )
                raise llm.ToolError(
                    "That extension or display name is unavailable. Continue helping the caller."
                ) from exc
            call_context.was_transferred = True
            call_context.transfer_extension = resolved_target.extension
            log.info(
                "call_transferred",
                extension_id=resolved_target.extension_id,
                extension=resolved_target.extension,
            )
            return f"The caller was transferred to extension {resolved_target.extension}."
        if config.use_realtime:
            session: AgentSession[None] = AgentSession(
                llm=create_realtime_llm(config, settings),
                tts=create_realtime_tts(config, settings),
            )
        else:
            session = AgentSession(
                vad=create_vad(),
                stt=create_stt(config, settings),
                llm=create_llm(config, settings),
                tts=create_tts(config, settings),
            )
        transcripts = TranscriptService(backend, call_context)
        lifecycle = CallLifecycleService(
            backend,
            call_context,
            OpenAICallAnalyzer(settings),
        )
        closed = asyncio.Event()

        @session.on("conversation_item_added")
        def on_conversation_item_added(event: object) -> None:
            transcripts.handle_item(getattr(event, "item", None))

        @session.on("error")
        def on_error(event: object) -> None:
            log.error("agent_session_error", error=str(getattr(event, "error", "unknown")))

        @session.on("close")
        def on_close(_: object) -> None:
            closed.set()

        await session.start(
            room=ctx.room,
            agent=KnowledgeAgent(
                instructions=compose_instructions(config, allow_transfer=not web_test),
                tools=[end_call_tool] if web_test else [end_call_tool, transfer_to_extension],
                knowledge=knowledge,
                retrieval_top_k=settings.knowledge_retrieval_top_k,
                retrieval_max_chars=settings.knowledge_retrieval_max_chars,
            ),
            room_options=room_io.RoomOptions(participant_identity=sip.participant_identity),
        )
        if sip.outbound:
            recipient = (config.outbound_context or {}).get("recipient") or {}
            first_name = recipient.get("first_name") or ""
            objective = (config.outbound_context or {}).get("objective") or (
                "the reason for this call"
            )
            outbound_language = recipient.get("language") or config.language
            await session.generate_reply(
                instructions=(
                    f"Start the outbound call naturally in {outbound_language}. "
                    f"Address the recipient as {first_name!r} if available, identify "
                    "the company, disclose that you are an AI assistant, and briefly "
                    f"state this purpose: {objective}. "
                    "Then pause for their response."
                )
            )
        else:
            greeting = config.greeting_message or (
                f"Hello, you are speaking with {config.agent_name}."
            )
            await session.generate_reply(
                instructions=f"Say this greeting once, naturally, in {config.language}: {greeting}"
            )
        log.info("call_session_started")
        reason = "caller_disconnected"
        max_duration_seconds = (
            settings.web_test_call_max_duration_seconds
            if web_test
            else settings.call_max_duration_seconds
        )
        try:
            await asyncio.wait_for(closed.wait(), timeout=max_duration_seconds)
        except TimeoutError:
            reason = "maximum_duration_reached"
            await session.aclose()
        finally:
            if hangup_requested:
                reason = "agent_hangup"
            await transcripts.flush()
            await lifecycle.complete(reason=reason)
            log.info("call_session_completed", reason=reason)
