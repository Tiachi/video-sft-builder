class PipelineError(Exception):
    """Expected, user-readable failure; messages must never contain credentials."""


class ConfigError(PipelineError):
    pass


class Blocked(PipelineError):
    """Resource/capability constraint; pending, not a quality rejection."""


class ProtocolError(PipelineError):
    pass


class UnknownExecution(PipelineError):
    """A sent request cannot be safely repeated."""


class BudgetBreach(PipelineError):
    pass
