"""MCP server entrypoint and lifecycle dependency management."""

import logging
import sys
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager

from mcp.server.mcpserver import MCPServer

from app.api.dependencies import get_sandbox_engine, get_settings
from app.db.session import SessionLocal
from app.mcp.tools import register_mcp_tools
from app.services.sandbox_lifecycle_service import SandboxLifecycleService

logger = logging.getLogger(__name__)


@contextmanager
def default_service_factory() -> Generator[SandboxLifecycleService, None, None]:
    """Provide a SandboxLifecycleService backed by a dedicated database session."""
    db = SessionLocal()
    try:
        service = SandboxLifecycleService(
            db=db,
            config=get_settings(),
            engine=get_sandbox_engine(),
        )
        yield service
    finally:
        db.close()


def create_mcp_server(
    service_factory: Callable[[], AbstractContextManager[SandboxLifecycleService]] | None = None,
) -> MCPServer:
    """Create and configure an MCPServer instance with registered sandbox tools."""
    factory = service_factory or default_service_factory
    server = MCPServer(
        name="ai-sandbox-platform",
        version="0.1.0",
        description=(
            "Model Context Protocol (MCP) server providing secure, hardened, "
            "ephemeral sandbox execution sessions for AI agents."
        ),
    )
    register_mcp_tools(server=server, service_factory=factory)
    return server


def main() -> None:
    """Run the MCP server over standard I/O (stdio) transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # Preserve stdout for clean JSON-RPC protocol transport
    )
    logger.info("Initializing AI Sandbox Platform MCP Server (stdio transport)...")
    server = create_mcp_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
