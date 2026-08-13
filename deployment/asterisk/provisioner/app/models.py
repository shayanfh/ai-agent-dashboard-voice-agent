import ipaddress
import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.@+\-]+$")


class ConnectionSpec(BaseModel):
    company_id: uuid.UUID
    name: str = Field(min_length=2, max_length=255)
    provider: Literal["twilio", "generic_sip"]
    mode: Literal["twilio", "registration", "ip_trunk"]
    phone_number: str
    transport: Literal["udp", "tcp", "tls"] = "tcp"
    server_uri: str | None = Field(default=None, max_length=500)
    server_port: int | None = Field(default=None, ge=1, le=65535)
    allowed_addresses: list[str] = Field(default_factory=list, max_length=50)
    auth_username: str | None = Field(default=None, max_length=100)
    auth_password: str | None = Field(default=None, max_length=255)
    realm: str | None = Field(default=None, max_length=255)
    outbound_proxy: str | None = Field(default=None, max_length=500)
    public_sip_uri: str = Field(min_length=5, max_length=500)

    @field_validator(
        "name",
        "server_uri",
        "auth_username",
        "auth_password",
        "realm",
        "outbound_proxy",
        "public_sip_uri",
    )
    @classmethod
    def reject_config_injection(cls, value: str | None) -> str | None:
        if value and any(char in value for char in ("\r", "\n")):
            raise ValueError("configuration values cannot contain newlines")
        return value

    @model_validator(mode="after")
    def validate_mode(self) -> "ConnectionSpec":
        if not E164.fullmatch(self.phone_number):
            raise ValueError("phone_number must be E.164")
        if self.mode == "twilio" and self.provider != "twilio":
            raise ValueError("twilio mode requires the twilio provider")
        if self.mode == "registration":
            if self.provider != "generic_sip":
                raise ValueError("registration mode requires generic_sip")
            if not all((self.server_uri, self.auth_username, self.auth_password)):
                raise ValueError("registration requires server and credentials")
            if not SAFE_ID.fullmatch(self.auth_username or ""):
                raise ValueError("auth_username contains unsupported characters")
        if self.mode == "ip_trunk":
            if self.provider != "generic_sip" or not self.allowed_addresses:
                raise ValueError("ip_trunk requires generic_sip and provider addresses")
        for address in self.allowed_addresses:
            ipaddress.ip_network(address, strict=False)
        return self


class ConnectionResponse(BaseModel):
    resource_id: str
    state: Literal["configured", "registering", "registered", "unregistered"]
    provider_setup: dict = Field(default_factory=dict)


class ExtensionSpec(BaseModel):
    company_id: uuid.UUID
    extension: str = Field(pattern=r"^[1-9][0-9]{1,5}$")
    display_name: str = Field(min_length=2, max_length=100)
    sip_username: str = Field(min_length=4, max_length=100)
    sip_password: str = Field(min_length=16, max_length=255)
    transport: Literal["udp", "tcp", "tls"] = "udp"
    enabled: bool = True

    @field_validator("display_name", "sip_username", "sip_password")
    @classmethod
    def validate_configuration_value(cls, value: str) -> str:
        if any(char in value for char in ("\r", "\n")):
            raise ValueError("configuration values cannot contain newlines")
        return value

    @model_validator(mode="after")
    def validate_username(self) -> "ExtensionSpec":
        if not SAFE_ID.fullmatch(self.sip_username):
            raise ValueError("sip_username contains unsupported characters")
        return self


class ExtensionResponse(BaseModel):
    resource_id: str
    state: Literal["configured", "disabled"]
