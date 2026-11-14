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


def _is_container_active(container: Container) -> bool:
    """Return True if the container's reloaded State indicates it is still running/active."""
    attrs = getattr(container, "attrs", None)
    if not isinstance(attrs, dict):
        return False
    state = attrs.get("State")
    if not isinstance(state, dict):
        return False
    return bool(state.get("Running") or state.get("Paused") or state.get("Restarting"))


def cleanup_container_safely(
    container: Container | None,
    sandbox_id: str,
    config: SandboxSettings,
) -> bool:
    """Safely and idempotently terminate and remove an ephemeral container and volumes.

    Guarantees:
    - Only operates if container object is valid.
    - Double checks project labels before any destructive action.
    - Never terminates infrastructure services (e.g. ai-sandbox-db).
    - Verifies the container is stopped before removing container and anonymous volumes.
    - Idempotently ignores NotFound exceptions.
    """
    if container is None:
        return True

    cid = container.id[:12] if hasattr(container, "id") and container.id else "unknown"

    try:
        # Reloaded labels are the only source of authority for destructive operations.
        try:
            container.reload()
            labels = container.attrs.get("Config", {}).get("Labels", {})
            if labels.get("project") != config.PROJECT_LABEL:
                logger.warning(
                    f"Refusing to delete container {cid}: project ownership does not match"
                )
                return False
            if labels.get("managed-by") != config.MANAGED_BY_LABEL:
                logger.warning(
                    f"Refusing to delete container {cid}: manager ownership does not match"
                )
                return False
            if labels.get("sandbox_id") != sandbox_id:
                logger.warning(
                    f"Refusing to delete container {cid}: sandbox ownership does not match"
                )
                return False
            if labels.get("service") == "ai-sandbox-db":
                logger.warning(f"Refusing to delete database infrastructure container {cid}")
                return False
        except NotFound:
            # Already removed
            return True
        except Exception as exc:
            logger.error(f"Refusing to delete container {cid}: ownership reload failed: {exc}")
            return False

        # Terminate container and verify it is stopped before removing anonymous volumes.
        kill_error: Exception | None = None
        try:
            container.kill()
        except NotFound:
            return True
        except Exception as exc:
            msg = str(exc).lower()
            if "not running" not in msg and "no such container" not in msg:
                kill_error = exc

        if _is_container_active(container) or kill_error is not None:
            try:
                container.reload()
            except NotFound:
                return True
            except Exception as exc:
                logger.error(f"Failed to reload container {cid} after kill attempt: {exc}")
                return False

            if _is_container_active(container):
                try:
                    container.stop(timeout=0)
                    container.reload()
                except NotFound:
                    return True
                except Exception as exc:
                    logger.error(f"Failed to stop running container {cid}: {exc}")
                    return False

                if _is_container_active(container):
                    logger.error(
                        f"Refusing to remove volumes for {cid}: container is still running"
                    )
                    return False
            elif kill_error is not None and not isinstance(container.attrs.get("State"), dict):
                logger.error(f"Failed to terminate container {cid}: {kill_error}")
                return False

        # Remove stopped container and any anonymous container-scoped volumes.
        # Never fall back to removing without `v=True`, which would leak anonymous volumes.
        try:
            container.remove(v=True, force=True)
            logger.info(f"Container {cid} (sandbox_id={sandbox_id}) successfully removed.")
            return True
        except NotFound:
            return True
        except Exception as exc:
            logger.error(f"Failed to remove container and volumes for {cid}: {exc}")
            return False

    except Exception as exc:
        logger.error(f"Unexpected error during container cleanup for {cid}: {exc}")
        return False
