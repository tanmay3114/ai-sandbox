"""HTTP admission control for the Docker-backed public API."""

from secrets import compare_digest

from fastapi import Depends, Header, HTTPException, status

from app.api.dependencies import get_settings
from app.core.config import SandboxSettings


def require_api_key(
    x_api_key: str | None = Header(default=None),
    config: SandboxSettings = Depends(get_settings),
) -> None:
    """Require a configured API key outside explicitly local environments.

    MCP uses stdio and remains a local-process integration; this dependency
    protects only the network-facing FastAPI routes that can reach Docker.
    """
    if not config.api_auth_required:
        return

    expected_key = config.API_KEY
    if (
        expected_key is None
        or x_api_key is None
        or not compare_digest(
            x_api_key,
            expected_key.get_secret_value(),
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid X-API-Key is required.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
