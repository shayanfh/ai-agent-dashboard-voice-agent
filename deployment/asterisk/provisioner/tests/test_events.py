import pytest
from app.config import Settings
from app.events import OutboundEventMonitor


def settings() -> Settings:
    return Settings(
        _env_file=None,
        provisioner_api_key="test-key",
        public_sip_uri="sip:asterisk.test:5060;transport=udp",
        livekit_sip_uri="sip:livekit.test:5060;transport=udp",
        ami_username="provisioner",
        ami_password="secret",
        backend_outbound_callback_url="https://backend.test/internal/outbound/events",
        backend_internal_api_key="internal-key",
    )


@pytest.mark.asyncio
async def test_opt_out_is_terminal_and_clears_event_correlation() -> None:
    monitor = OutboundEventMonitor(settings())
    callbacks: list[tuple[str, str]] = []

    async def callback(attempt_id: str, status: str, *args, **kwargs) -> None:
        callbacks.append((attempt_id, status))

    monitor._callback = callback
    monitor.register("attempt-1")
    monitor.by_unique_id["channel-1"] = "attempt-1"

    await monitor._handle(
        {
            "Event": "UserEvent",
            "UserEvent": "AIOutboundOptOut",
            "AttemptID": "attempt-1",
            "Uniqueid": "channel-1",
        }
    )
    await monitor._handle(
        {"Event": "Hangup", "Uniqueid": "channel-1", "Cause": "16"}
    )

    assert callbacks == [("attempt-1", "do_not_call")]
    assert "attempt-1" not in monitor.pending
    assert "channel-1" not in monitor.by_unique_id


def test_disabled_monitor_does_not_accumulate_attempts() -> None:
    disabled = settings().model_copy(
        update={"backend_outbound_callback_url": "", "backend_internal_api_key": ""}
    )
    monitor = OutboundEventMonitor(disabled)

    monitor.register("attempt-1")

    assert monitor.pending == {}
