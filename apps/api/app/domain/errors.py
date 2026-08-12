class AgentStudioError(Exception):
    """Base error for application failures."""


class EntityNotFoundError(AgentStudioError):
    """Raised when a requested entity does not exist."""


class ProviderNotConfiguredError(AgentStudioError):
    """Raised when an opt-in provider has no credentials."""


class ToolExecutionError(AgentStudioError):
    """Raised when a tool cannot safely complete."""


class ToolValidationError(ToolExecutionError):
    """Raised when tool arguments are invalid or unsafe."""


class ToolNotFoundError(ToolExecutionError):
    """Raised when a tool is not registered."""
