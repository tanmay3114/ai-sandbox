"""Centralized selection of supported sandbox infrastructure backends."""

from app.core.config import SandboxSettings
from app.core.exceptions import InvalidRuntimeError
from app.sandbox.backend import SandboxBackend
from app.sandbox.docker_backend import DockerSandboxBackend
from app.sandbox.qemu_backend import QemuSandboxBackend


def create_sandbox_backend(config: SandboxSettings) -> SandboxBackend:
    """Construct a backend instance; process sharing belongs to the DI provider.

    Callers that need application-wide concurrency control must obtain the cached
    ``get_sandbox_backend`` dependency rather than invoking this constructor.
    """
    backend = config.BACKEND.strip().lower()
    if backend == "docker":
        return DockerSandboxBackend(config=config)
    if backend == "qemu":
        return QemuSandboxBackend(config=config)
    raise InvalidRuntimeError(
        f"Unsupported sandbox backend '{config.BACKEND}'. Supported backends: 'docker', 'qemu'."
    )
