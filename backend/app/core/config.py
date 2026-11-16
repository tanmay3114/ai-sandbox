"""Application settings and resource limits configuration."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PYTHON_RUNTIME_IMAGE = (
    "python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"
)


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
    BACKEND: str = Field(
        default="docker",
        description="Execution backend identifier ('docker' or 'qemu')",
    )
    GLOBAL_CONCURRENCY_LIMIT: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Maximum number of simultaneous active sandbox executions on this instance",
    )

    # QEMU Virtualization Backend Configuration
    QEMU_BINARY: str = Field(
        default="qemu-system-aarch64",
        description="QEMU system emulator executable for ARM64 Linux guests",
    )
    QEMU_IMG_BINARY: str = Field(
        default="qemu-img",
        description="QEMU disk image manipulation utility executable",
    )
    QEMU_ACCELERATOR: str = Field(
        default="hvf",
        description="QEMU hardware virtualization accelerator ('hvf', 'kvm', or 'tcg')",
    )
    QEMU_MACHINE: str = Field(
        default="virt",
        description="QEMU ARM64 machine model",
    )
    QEMU_CPU: str = Field(
        default="host",
        description="QEMU CPU model ('host' for HVF/KVM, 'max' or 'cortex-a72' for TCG)",
    )
    QEMU_GUEST_ARCH: str = Field(
        default="aarch64",
        description="Target guest architecture (must normalize to 'aarch64')",
    )
    QEMU_MEMORY_MB: int = Field(
        default=256,
        ge=128,
        le=4096,
        description="Default guest VM RAM allocation in MiB when not overridden by policy",
    )
    QEMU_VCPUS: int = Field(
        default=1,
        ge=1,
        le=8,
        description="Number of virtual CPUs allocated to each ephemeral VM",
    )
    QEMU_DISK_SIZE: str = Field(
        default="512M",
        description="Size of disposable per-execution qcow2 overlay disk",
    )
    QEMU_IMAGE_DIR: Path = Field(
        default=_REPO_ROOT / ".sandboxes" / "qemu" / "images",
        description="Directory containing immutable ARM64 guest kernel, initramfs, and base image",
    )
    QEMU_KERNEL_PATH: Path | None = Field(
        default=None,
        description="Optional explicit path to the ARM64 guest kernel image",
    )
    QEMU_INITRD_PATH: Path | None = Field(
        default=None,
        description="Optional explicit path to the ARM64 guest initramfs image",
    )
    QEMU_BASE_IMAGE_PATH: Path | None = Field(
        default=None,
        description="Optional explicit path to the immutable ARM64 guest rootfs qcow2 image",
    )
    QEMU_KERNEL_SHA256: str | None = Field(
        default=None,
        description="Optional pinned SHA-256 hex digest for the guest kernel",
    )
    QEMU_INITRD_SHA256: str | None = Field(
        default=None,
        description="Optional pinned SHA-256 hex digest for the guest initramfs",
    )
    QEMU_BASE_IMAGE_SHA256: str | None = Field(
        default=None,
        description="Optional pinned SHA-256 hex digest for the guest base qcow2 image",
    )
    QEMU_RUNTIME_DIR: Path = Field(
        default=_REPO_ROOT / ".sandboxes" / "qemu" / "runtime",
        description="Private host base directory for per-execution VM sockets, overlays, and PIDs",
    )
    QEMU_BOOT_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        ge=0.5,
        le=60.0,
        description="Maximum time in seconds to wait for VM boot and guest agent readiness",
    )
    QEMU_AGENT_TIMEOUT_SECONDS: float = Field(
        default=5.0,
        ge=0.5,
        le=60.0,
        description="Timeout in seconds for individual host-to-guest control RPCs",
    )
    QEMU_MAX_CONCURRENT_VMS: int | None = Field(
        default=None,
        ge=1,
        le=32,
        description="Maximum simultaneous ephemeral VMs (defaults to GLOBAL_CONCURRENCY_LIMIT)",
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

    # API admission control
    ENVIRONMENT: Literal["development", "test", "staging", "production"] = "development"
    API_KEY: SecretStr | None = Field(
        default=None,
        description="Required X-API-Key value when running in staging or production",
    )

    # Image & Runtime
    BASE_IMAGE: str = Field(
        default=_PYTHON_RUNTIME_IMAGE,
        description="Immutable digest-pinned base image for Python execution",
    )
    ALLOWED_RUNTIMES: dict[str, str] = Field(
        default_factory=lambda: {"python": _PYTHON_RUNTIME_IMAGE},
        description="Strict map of allowed runtime identifiers to digest-pinned container images",
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

    # Workspace & Filesystem Limits
    WORKSPACE_DIR: Path = Field(
        default=_REPO_ROOT / ".sandboxes" / "workspaces",
        description="Base host directory for storing persistent sandbox workspaces",
    )
    WORKSPACE_TMPFS_SIZE: str = Field(
        default="64m",
        description="Size limit for the writable in-container /workspace tmpfs mount",
    )
    MAX_FILE_SIZE_BYTES: int = Field(
        default=5 * 1024 * 1024,
        ge=1,
        le=50 * 1024 * 1024,
        description="Hard limit on individual file size in bytes (default: 5 MB)",
    )
    MAX_WORKSPACE_SIZE_BYTES: int = Field(
        default=25 * 1024 * 1024,
        ge=1,
        le=200 * 1024 * 1024,
        description="Total workspace storage limit per sandbox session (default: 25 MB)",
    )
    MAX_FILE_COUNT: int = Field(
        default=250,
        ge=1,
        le=5000,
        description="Maximum total files allowed in a single sandbox workspace",
    )
    MAX_DIRECTORY_DEPTH: int = Field(
        default=8,
        ge=1,
        le=32,
        description="Maximum directory nesting depth allowed in a sandbox workspace",
    )
    MAX_PATH_LENGTH: int = Field(
        default=255,
        ge=1,
        le=1024,
        description="Maximum length of a relative file path in characters",
    )
    MAX_ARCHIVE_BYTES: int = Field(
        default=25 * 1024 * 1024,
        ge=1,
        le=100 * 1024 * 1024,
        description="Maximum raw compressed archive size for container synchronization",
    )
    MAX_DECOMPRESSED_BYTES: int = Field(
        default=25 * 1024 * 1024,
        ge=1,
        le=200 * 1024 * 1024,
        description="Maximum cumulative decompressed archive size for container synchronization",
    )
    MAX_ARCHIVE_ENTRIES: int = Field(
        default=250,
        ge=1,
        le=5000,
        description="Maximum entry count in a container synchronization archive",
    )
    MAX_FILE_LIST_ENTRIES: int = Field(
        default=500,
        ge=1,
        le=5000,
        description="Maximum entries returned in a file listing operation",
    )
    MAX_READ_RESPONSE_BYTES: int = Field(
        default=5 * 1024 * 1024,
        ge=1,
        le=50 * 1024 * 1024,
        description="Maximum size of file content returned in a read operation",
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
    AGENT_MAX_TOOL_CALLS: int = Field(
        default=30,
        ge=1,
        le=100,
        description="Maximum total tool calls permitted per agent task",
    )
    AGENT_MAX_TOOL_RESULT_BYTES: int = Field(
        default=64 * 1024,
        ge=1024,
        le=10 * 1024 * 1024,
        description="Maximum serialized size in bytes for a single tool result before truncation",
    )
    AGENT_MAX_CONSECUTIVE_REPEATS: int = Field(
        default=3,
        ge=2,
        le=10,
        description="Maximum consecutive identical tool calls before loop breaker engages",
    )

    @property
    def nano_cpus(self) -> int:
        """Calculate nano_cpus required by Docker Engine API."""
        return int(self.CPU_LIMIT * 1_000_000_000)

    @property
    def api_auth_required(self) -> bool:
        """Return whether public HTTP API calls must present the configured API key."""
        return self.ENVIRONMENT in {"staging", "production"}

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("BACKEND")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        backend = value.strip().lower()
        if backend not in {"docker", "qemu"}:
            raise ValueError(
                f"Unsupported sandbox backend '{value}'. Only 'docker' and 'qemu' are implemented."
            )
        return backend

    @field_validator("QEMU_ACCELERATOR")
    @classmethod
    def validate_qemu_accelerator(cls, value: str) -> str:
        accel = value.strip().lower()
        if accel not in {"hvf", "kvm", "tcg"}:
            raise ValueError(
                f"Unsupported QEMU accelerator '{value}'. Allowed values: 'hvf', 'kvm', 'tcg'."
            )
        return accel

    @field_validator("QEMU_GUEST_ARCH")
    @classmethod
    def validate_qemu_guest_arch(cls, value: str) -> str:
        arch = value.strip().lower()
        if arch in {"arm64", "aarch64"}:
            return "aarch64"
        raise ValueError(
            f"Unsupported QEMU guest architecture '{value}'. Only 'aarch64'/'arm64' is supported."
        )

    @field_validator("QEMU_MACHINE")
    @classmethod
    def validate_qemu_machine(cls, value: str) -> str:
        machine = value.strip()
        if not machine or not machine.startswith("virt"):
            raise ValueError(
                f"Unsupported QEMU machine model '{value}'. Must use ARM64 'virt' machine family."
            )
        return machine

    @field_validator("BASE_IMAGE")
    @classmethod
    def validate_base_image(cls, v: str) -> str:
        """Reject floating image tags so the trusted runtime is immutable."""
        image = v.strip()
        if not image or "@sha256:" not in image:
            raise ValueError(f"An immutable image digest is required for sandbox: {v}")
        return image

    @model_validator(mode="after")
    def validate_production_api_key(self) -> "SandboxSettings":
        """Make unauthenticated public API deployment an invalid configuration."""
        if self.api_auth_required and self.API_KEY is None:
            raise ValueError("SANDBOX_API_KEY is required in staging and production")
        configured_image = self.ALLOWED_RUNTIMES.get("python")
        if configured_image != self.BASE_IMAGE:
            raise ValueError("The allowed python runtime must match SANDBOX_BASE_IMAGE")
        if any("@sha256:" not in image for image in self.ALLOWED_RUNTIMES.values()):
            raise ValueError("Every allowed runtime image must use an immutable digest")
        return self


# Global default settings instance
settings = SandboxSettings()
