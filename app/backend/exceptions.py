class BackendError(Exception):
    pass


class BackendUnavailable(BackendError):
    pass


class AgentNotFound(BackendError):
    pass


class BackendRejected(BackendError):
    pass

