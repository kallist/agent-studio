class AgentStudioError(Exception):
    """Base error for application failures."""


class EntityNotFoundError(AgentStudioError):
    """Raised when a requested entity does not exist."""


class ProviderNotConfiguredError(AgentStudioError):
    """Raised when an opt-in provider has no credentials."""


class ProviderExecutionError(AgentStudioError):
    """Raised when a configured model provider cannot complete a decision."""


class InvalidAgentOutputError(AgentStudioError):
    """Raised when model output does not match the structured decision contract."""


class ToolExecutionError(AgentStudioError):
    """Raised when a tool cannot safely complete."""


class ToolValidationError(ToolExecutionError):
    """Raised when tool arguments are invalid or unsafe."""


class ToolNotFoundError(ToolExecutionError):
    """Raised when a tool is not registered."""


class ToolPermissionError(ToolExecutionError):
    """Raised when a run has not been granted a tool's required permissions."""
