from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    provisioner_api_key: str
    state_file: str = "/var/lib/asterisk-provisioner/connections.json"
    generated_pjsip_file: str = "/etc/asterisk/ai-agent-generated/pjsip.conf"
    generated_dialplan_file: str = "/etc/asterisk/ai-agent-generated/extensions.conf"
    public_sip_uri: str
    livekit_sip_uri: str
    livekit_auth_username: str | None = None
    livekit_auth_password: str | None = None
    livekit_transport_name: str = "0.0.0.0-udp"
    pjsip_udp_transport_name: str = "0.0.0.0-udp"
    pjsip_tcp_transport_name: str = "0.0.0.0-tcp"
    pjsip_tls_transport_name: str = "0.0.0.0-tls"
    twilio_signaling_cidrs: str = ""
    ami_host: str = "127.0.0.1"
    ami_port: int = 5038
    ami_username: str
    ami_password: str
    ami_timeout_seconds: float = 10
    enable_recording: bool = True
    recording_directory: str = "/var/spool/asterisk/monitor/ai-agent"
    recording_uploader: str = "/usr/local/bin/upload-asterisk-recording.sh"
    outbound_media_directory: str = "/var/lib/asterisk/sounds/ai-agent-generated"
    max_outbound_media_bytes: int = 20 * 1024 * 1024
    backend_outbound_callback_url: str = ""
    backend_internal_api_key: str = ""

    @property
    def twilio_cidrs(self) -> list[str]:
        return [item.strip() for item in self.twilio_signaling_cidrs.split(",") if item.strip()]

    def transport_name(self, protocol: str) -> str:
        return {
            "udp": self.pjsip_udp_transport_name,
            "tcp": self.pjsip_tcp_transport_name,
            "tls": self.pjsip_tls_transport_name,
        }[protocol]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
