class VoiceAgentError(Exception):
    """Base application exception."""


class ConfigurationError(VoiceAgentError):
    """A tenant or provider configuration is unusable."""


class CallerNotFoundError(VoiceAgentError):
    """No SIP caller joined the room."""

