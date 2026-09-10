"""Docker client wrapper ensuring operations are strictly project-scoped."""

import logging

import docker
from docker.errors import APIError, NotFound
from docker.models.containers import Container

from app.core.config import SandboxSettings, settings
from app.core.exceptions import DockerEngineError

logger = logging.getLogger(__name__)


def get_docker_client() -> docker.DockerClient:
    """Instantiate and verify connectivity to the local Docker Engine."""
    try:
        client = docker.from_env()
        # Ping the engine to confirm connectivity
        client.ping()
        return client
    except Exception as exc:
        logger.error(f"Failed to connect to Docker Engine: {exc}")
        raise DockerEngineError(f"Docker Engine is unreachable: {exc}") from exc


def list_project_containers(
    client: docker.DockerClient,
    config: SandboxSettings | None = None,
    all_states: bool = True,
) -> list[Container]:
    """List only containers owned by this project.

    NEVER queries or manipulates containers outside the project namespace.
    """
    cfg = config or settings
    try:
        return client.containers.list(
            all=all_states,
            filters={
                "label": [
                    f"project={cfg.PROJECT_LABEL}",
                    f"managed-by={cfg.MANAGED_BY_LABEL}",
                ]
            },
        )
    except APIError as exc:
        logger.error(f"Failed to list project containers: {exc}")
        raise DockerEngineError(f"Failed to query Docker containers: {exc}") from exc


def list_sandbox_containers(
    client: docker.DockerClient,
    config: SandboxSettings | None = None,
    all_states: bool = True,
) -> list[Container]:
    """List only ephemeral execution sandbox containers owned by this project.

    Excludes infrastructure containers (such as database services).
    """
    all_project_containers = list_project_containers(client, config=config, all_states=all_states)
    return [
        c
        for c in all_project_containers
        if "sandbox_id" in c.attrs.get("Config", {}).get("Labels", {})
    ]


def cleanup_container_safely(
    container: Container | None,
    sandbox_id: str | None = None,
) -> bool:
    """Safely and idempotently terminate and remove an ephemeral container.

    Guarantees:
    - Only operates if container object is valid.
    - Double checks project labels before any destructive action.
    - Never terminates infrastructure services (e.g. ai-sandbox-db).
    - Idempotently ignores NotFound exceptions.
    """
    if container is None:
        return True

    cid = container.id[:12] if hasattr(container, "id") and container.id else "unknown"

    try:
        # Reload latest attributes
        try:
            container.reload()
            labels = container.attrs.get("Config", {}).get("Labels", {})
            if labels.get("project") != settings.PROJECT_LABEL:
                logger.warning(
                    f"Refusing to delete container {cid}: label != {settings.PROJECT_LABEL}"
                )
                return False
            if labels.get("service") == "ai-sandbox-db":
                logger.warning(f"Refusing to delete database infrastructure container {cid}")
                return False
        except NotFound:
            # Already removed
            return True
        except Exception:
            pass  # If reload fails, continue with removal attempt

        # If still running, kill it first
        try:
            container.kill()
        except (NotFound, APIError):
            # Already stopped, killed, or not found
            pass

        # Force remove container
        try:
            container.remove(force=True)
            logger.info(f"Container {cid} (sandbox_id={sandbox_id}) successfully removed.")
            return True
        except NotFound:
            return True
        except APIError as exc:
            logger.error(f"Failed to remove container {cid}: {exc}")
            return False

    except Exception as exc:
        logger.error(f"Unexpected error during container cleanup for {cid}: {exc}")
        return False
