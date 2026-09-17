"""Application settings and resource limits configuration."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class SandboxSettings(BaseSettings):
    """Configuration settings for the sandbox runtime and security limits."""

    model_config = SettingsConfigDict(
        env_prefix="SANDBOX_",
        env_file=(_REPO_ROOT / ".env", _REPO_ROOT.parent / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Resource Limits
    MEMORY_LIMIT: str = Field(
        default="256m",
        description="Container RAM limit (e.g. 128m, 256m, 512m)",
    )
    MEMSWAP_LIMIT: str = Field(
        default="256m",
        description="Memory + swap limit; setting equal to MEMORY_LIMIT disables swap escape",
    )
    CPU_LIMIT: float = Field(
        default=0.5,
        ge=0.1,
        le=4.0,
        description="CPU limit fraction (e.g. 0.5 for 50% of one core)",
    )
    TIMEOUT_SECONDS: float = Field(
        default=5.0,
        ge=0.5,
        le=60.0,
        description="Execution timeout in seconds",
    )
    MAX_STDOUT_BYTES: int = Field(
        default=65536,
        ge=1024,
        le=10 * 1024 * 1024,
        description="Hard byte limit on captured stdout before truncation",
    )
    MAX_STDERR_BYTES: int = Field(
        default=65536,
        ge=1024,
        le=10 * 1024 * 1024,
        description="Hard byte limit on captured stderr before truncation",
    )
    PIDS_LIMIT: int = Field(
        default=32,
        ge=8,
        le=256,
        description="Maximum concurrent processes inside container (fork bomb prevention)",
    )
    TMPFS_SIZE: str = Field(
        default="32m",
        description="Size limit for the writable /tmp tmpfs mount",
    )

    # Concurrency
    GLOBAL_CONCURRENCY_LIMIT: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Maximum number of simultaneous active sandbox executions on this instance",
    )

    # Database & Persistence
    DATABASE_URL: str = Field(
        description="PostgreSQL database connection URL supplied by SANDBOX_DATABASE_URL",
    )
    DEFAULT_SANDBOX_TTL_SECONDS: int = Field(
        default=300,
        ge=10,
        le=86400,
        description="Default lifespan in seconds before an inactive sandbox session expires",
    )
    MIN_SANDBOX_TTL_SECONDS: int = 10
    MAX_SANDBOX_TTL_SECONDS: int = 86400

    # Image & Runtime
    BASE_IMAGE: str = Field(
        default="python:3.12-slim",
        description="Pinned base image for Python execution",
    )
    ALLOWED_RUNTIMES: dict[str, str] = Field(
        default_factory=lambda: {"python": "python:3.12-slim"},
        description="Strict map of allowed runtime identifiers to pinned container images",
    )

    # Metadata & Tracking
    PROJECT_LABEL: str = "ai-sandbox"
    MANAGED_BY_LABEL: str = "ai-sandbox-platform"

    # CORS Configuration
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        description="Strictly allowed frontend development origins for CORS",
    )

    # LLM Provider Configuration
    LLM_PROVIDER: str = Field(
        default="gemini",
        description="Active LLM provider (e.g. 'gemini', 'openai', 'groq')",
    )
    LLM_API_KEY: str | None = Field(
        default=None,
        description="API key for LLM provider (supplied by SANDBOX_LLM_API_KEY)",
    )
    LLM_MODEL: str = Field(
        default="gemini-2.5-flash",
        description="Default model identifier to use (e.g. 'gemini-2.5-flash')",
    )
    LLM_BASE_URL: str | None = Field(
        default=None,
        description="Optional custom base URL for OpenAI-compatible proxies or local engines",
    )
    LLM_TEMPERATURE: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for LLM completions",
    )

    # Groq Provider Configuration
    GROQ_API_KEY: str | None = Field(
        default=None,
        description="API key for Groq provider (supplied by SANDBOX_GROQ_API_KEY)",
    )
    GROQ_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Default model identifier to use for Groq (e.g. 'openai/gpt-oss-120b')",
    )
    GROQ_BASE_URL: str = Field(
        default="https://api.groq.com/openai/v1",
        description="Base URL for Groq's OpenAI-compatible endpoint",
    )

    # Agent Loop Bounded Execution
    AGENT_MAX_ITERATIONS: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum iterations allowed in an agent tool-calling loop",
    )
    AGENT_REQUEST_TIMEOUT: float = Field(
        default=60.0,
        ge=1.0,
        le=300.0,
        description="Overall timeout in seconds for agent request execution",
    )

    @property
    def nano_cpus(self) -> int:
        """Calculate nano_cpus required by Docker Engine API."""
        return int(self.CPU_LIMIT * 1_000_000_000)

    @field_validator("BASE_IMAGE")
    @classmethod
    def validate_base_image(cls, v: str) -> str:
        """Prevent arbitrary or floating dangerous image references."""
        if not v or v.strip().endswith(":latest"):
            raise ValueError(f"Floating 'latest' or empty image tag is disallowed for sandbox: {v}")
        return v.strip()


# Global default settings instance
settings = SandboxSettings()
