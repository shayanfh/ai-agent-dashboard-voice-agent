import asyncio
import uuid

from app.config import Settings


class AmiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def command(self, command: str) -> str:
        return await asyncio.wait_for(
            self._command(command), timeout=self.settings.ami_timeout_seconds
        )

    async def _command(self, command: str) -> str:
        reader, writer = await asyncio.open_connection(
            self.settings.ami_host, self.settings.ami_port
        )
        try:
            await reader.readline()
            await self._action(
                reader,
                writer,
                {
                    "Action": "Login",
                    "Username": self.settings.ami_username,
                    "Secret": self.settings.ami_password,
                    "Events": "off",
                },
            )
            response = await self._action(
                reader, writer, {"Action": "Command", "Command": command}
            )
            if response.get("Response") not in ("Success", "Follows"):
                raise RuntimeError(response.get("Message", "AMI command failed"))
            return "\n".join(response.get("Output", []))
        finally:
            writer.close()
            await writer.wait_closed()

    async def _action(self, reader, writer, fields: dict[str, str]) -> dict:
        action_id = uuid.uuid4().hex
        payload = {**fields, "ActionID": action_id}
        writer.write(
            ("\r\n".join(f"{key}: {value}" for key, value in payload.items()) + "\r\n\r\n").encode()
        )
        await writer.drain()
        raw = await reader.readuntil(b"\r\n\r\n")
        decoded = raw.decode(errors="replace")
        result: dict[str, str | list[str]] = {}
        for line in decoded.split("\r\n"):
            if ": " not in line:
                continue
            key, value = line.split(": ", 1)
            if key == "Output":
                result.setdefault("Output", []).append(value)
            else:
                result[key] = value
        command_output_follows = (
            result.get("Response") == "Follows"
            or (
                fields.get("Action") == "Command"
                and result.get("Response") == "Error"
                and result.get("Message") == "Command output follows"
            )
        )
        if command_output_follows:
            # FreePBX/Asterisk versions differ here: some return
            # `Response: Follows`, while others return `Response: Error` with
            # the compatibility message `Command output follows` even though
            # the CLI command ran successfully.
            result["Response"] = "Follows"
            output = result.setdefault("Output", [])
            if "--END COMMAND--" not in decoded:
                while True:
                    line = (await reader.readline()).decode(errors="replace").rstrip("\r\n")
                    if line == "--END COMMAND--" or not line:
                        break
                    output.append(line.removeprefix("Output: "))
        if result.get("Response") == "Error":
            raise RuntimeError(str(result.get("Message", "AMI action failed")))
        return result

    async def reload(self) -> None:
        await self.command("pjsip reload")
        await self.command("dialplan reload")
