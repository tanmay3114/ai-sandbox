"""Custom domain exceptions for the sandbox platform."""


class SandboxPlatformError(Exception):
    """Base exception for all sandbox platform errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SandboxTimeoutError(SandboxPlatformError):
    """Raised when sandbox execution exceeds configured timeout."""

    pass


class ConcurrencyLimitError(SandboxPlatformError):
    """Raised when execution request exceeds global concurrency capacity."""

    pass


class ResourceLimitError(SandboxPlatformError):
    """Raised when requested resources exceed allowed limits."""

    pass


class DockerEngineError(SandboxPlatformError):
    """Raised when an underlying Docker Engine operation fails unexpectedly."""

    pass


class QemuEngineError(SandboxPlatformError):
    """Raised when an underlying QEMU runtime or guest VM operation fails unexpectedly."""

    pass


class QemuProtocolError(QemuEngineError):
    """Raised when host-to-guest communication violates the framed protocol."""

    pass


class QemuAgentTimeoutError(QemuEngineError):
    """Raised when the QEMU guest agent fails to respond within the configured deadline."""

    pass


class InvalidRuntimeError(SandboxPlatformError):
    """Raised when an unsupported or unapproved runtime is requested."""

    pass


class OutputLimitExceededError(SandboxPlatformError):
    """Raised when output collection exceeds hard stream limits."""

    pass


class SandboxNotFoundError(SandboxPlatformError):
    """Raised when requested sandbox ID does not exist."""

    pass


class SandboxExpiredError(SandboxPlatformError):
    """Raised when an operation is attempted on an expired sandbox."""

    pass


class SandboxDestroyedError(SandboxPlatformError):
    """Raised when an operation is attempted on a destroyed sandbox."""

    pass


class ExecutionNotFoundError(SandboxPlatformError):
    """Raised when requested execution ID does not exist for a sandbox."""

    pass


class LLMProviderError(SandboxPlatformError):
    """Raised when an underlying LLM provider operation fails."""

    pass


class AgentTimeoutError(SandboxPlatformError):
    """Raised when an agent execution loop exceeds configured timeout."""

    pass


class AgentMaxIterationsError(SandboxPlatformError):
    """Raised when an agent execution loop exceeds maximum permitted tool iterations."""

    pass


class AgentMaxToolCallsError(SandboxPlatformError):
    """Raised when an agent execution loop exceeds maximum permitted total tool calls."""

    pass


class AgentCancelledError(SandboxPlatformError):
    """Raised when an active agent task is explicitly cancelled."""

    pass


class AgentSecurityError(SandboxPlatformError):
    """Raised when an agent tool call attempts cross-sandbox access or security violation."""

    pass


class AgentTaskNotFoundError(SandboxPlatformError):
    """Raised when a requested agent task ID does not exist."""

    pass


class PathTraversalError(SandboxPlatformError):
    """Raised when a file path attempts to escape the sandbox workspace."""

    pass


class SandboxFileNotFoundError(SandboxPlatformError):
    """Raised when a requested file or directory does not exist in the sandbox workspace."""

    pass


class FileQuotaExceededError(SandboxPlatformError):
    """Raised when a file operation exceeds configured workspace size or file count limits."""

    pass


class InvalidFileEncodingError(SandboxPlatformError):
    """Raised when file content cannot be encoded or decoded with the specified format."""

    pass


class WorkspaceCleanupError(SandboxPlatformError):
    """Raised when persistent workspace directory deletion fails during sandbox cleanup."""

    pass


class WorkspaceRollbackError(WorkspaceCleanupError):
    """Raised when staging workspace commit fails and automatic backup rollback also fails."""

    pass
