import asyncio

import pytest
from app.ami import AmiClient
from app.config import Settings


class FakeWriter:
    def __init__(self) -> None:
        self.payload = b""

    def write(self, payload: bytes) -> None:
        self.payload += payload

    async def drain(self) -> None:
        return None


def settings() -> Settings:
    return Settings(
        _env_file=None,
        provisioner_api_key="test-key",
        public_sip_uri="sip:asterisk.test:5060;transport=udp",
        livekit_sip_uri="sip:livekit.test:5060;transport=udp",
        ami_username="provisioner",
        ami_password="secret",
    )


@pytest.mark.asyncio
async def test_freepbx_command_output_follows_compatibility_response() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(
        b"Response: Error\r\n"
        b"Message: Command output follows\r\n"
        b"\r\n"
        b"Output: Module 'res_pjsip.so' reloaded successfully.\r\n"
        b"--END COMMAND--\r\n"
    )
    reader.feed_eof()
    writer = FakeWriter()

    response = await AmiClient(settings())._action(
        reader,
        writer,
        {"Action": "Command", "Command": "pjsip reload"},
    )

    assert response["Response"] == "Follows"
    assert response["Output"] == ["Module 'res_pjsip.so' reloaded successfully."]
    assert b"Command: pjsip reload" in writer.payload


@pytest.mark.asyncio
async def test_real_ami_error_is_still_rejected() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"Response: Error\r\nMessage: Permission denied\r\n\r\n")
    reader.feed_eof()

    with pytest.raises(RuntimeError, match="Permission denied"):
        await AmiClient(settings())._action(
            reader,
            FakeWriter(),
            {"Action": "Command", "Command": "pjsip reload"},
        )
