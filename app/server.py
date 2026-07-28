import structlog
from livekit import agents
from livekit.agents import AgentServer

from app.agent.runtime import run_inbound_call
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger()
server = AgentServer()


@server.rtc_session(agent_name=settings.livekit_agent_name)
async def inbound_agent(ctx: agents.JobContext) -> None:
    try:
        await run_inbound_call(ctx, settings)
    except Exception:
        logger.exception("inbound_call_failed", room_name=ctx.room.name)

