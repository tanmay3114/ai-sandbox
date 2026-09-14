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


class SecurityPolicyViolationError(SandboxPlatformError):
    """Raised when a request violates platform security policies or invariants."""
    pass



