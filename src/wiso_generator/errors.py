class AgentError(Exception):
    """Base WISO Agent error."""


class AgentConfigurationError(AgentError):
    pass


class ProviderError(AgentError):
    pass
