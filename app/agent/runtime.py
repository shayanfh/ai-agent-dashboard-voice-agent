import asyncio
from uuid import uuid4

import structlog
from livekit import agents, rtc
from livekit.agents import Agent, AgentSession, room_io

from app.agent.context import CallContext
from app.agent.instructions import compose_instructions
from app.backend.client import DashboardBackendClient
from app.backend.schemas import CallCreate
from app.core.config import Settings
from app.core.exceptions import CallerNotFoundError
from app.providers.factories import create_llm, create_stt, create_tts, create_vad
from app.services.call_service import CallLifecycleService
from app.services.transcript_service import TranscriptService
from app.telephony.attributes import extract_sip_call_info

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


async def run_inbound_call(ctx: agents.JobContext, settings: Settings) -> None:
    correlation_id = str(uuid4())
    await ctx.connect()
    participant = await wait_for_sip_participant(ctx, settings.caller_wait_timeout_seconds)
    sip = extract_sip_call_info(
        participant, room_name=ctx.room.name, job_metadata=ctx.job.metadata
    )
    logger.info(
        "sip_routing_resolved",
        room_name=sip.room_name,
        caller_number=sip.caller_number,
        called_number=sip.called_number,
        destination_extension=sip.destination_extension,
        sip_trunk_id=sip.sip_trunk_id,
        participant_identity=sip.participant_identity,
    )
    if not sip.routing_number:
        raise CallerNotFoundError("Called number/extension is missing from SIP attributes")

    async with DashboardBackendClient(settings) as backend:
        config = await backend.resolve_agent(
            phone_number=sip.called_number or sip.routing_number,
            extension=sip.destination_extension,
            correlation_id=correlation_id,
        )
        created = await backend.create_call(
            CallCreate(
                phone_number=sip.called_number or sip.routing_number,
                extension=sip.destination_extension,
                caller_number=sip.caller_number,
                livekit_room_name=sip.room_name,
            ),
            correlation_id=correlation_id,
            idempotency_key=f"call:{sip.sip_call_id or sip.room_name}",
        )
        call_context = CallContext(
            call_id=created.call_id,
            correlation_id=correlation_id,
            company_id=config.company_id,
            agent_id=config.agent_id,
            sip=sip,
            agent_configuration=config,
        )
        log = logger.bind(
            call_id=created.call_id,
            company_id=config.company_id,
            agent_id=config.agent_id,
            room_name=sip.room_name,
            participant_identity=sip.participant_identity,
            correlation_id=correlation_id,
        )
        session: AgentSession[None] = AgentSession(
            vad=create_vad(),
            stt=create_stt(config, settings),
            llm=create_llm(config, settings),
            tts=create_tts(config, settings),
        )
        transcripts = TranscriptService(backend, call_context)
        lifecycle = CallLifecycleService(backend, call_context)
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
            agent=Agent(instructions=compose_instructions(config)),
            room_options=room_io.RoomOptions(participant_identity=sip.participant_identity),
        )
        greeting = config.greeting_message or f"Hello, you are speaking with {config.agent_name}."
        await session.generate_reply(
            instructions=f"Say this greeting once, naturally, in {config.language}: {greeting}"
        )
        log.info("call_session_started")
        reason = "caller_disconnected"
        try:
            await asyncio.wait_for(closed.wait(), timeout=settings.call_max_duration_seconds)
        except TimeoutError:
            reason = "maximum_duration_reached"
            await session.aclose()
        finally:
            await transcripts.flush()
            await lifecycle.complete(reason=reason)
            log.info("call_session_completed", reason=reason)
