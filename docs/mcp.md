# Model Context Protocol (MCP) Integration Guide

This document explains the Model Context Protocol (MCP) server integration for the **Cloud-Based Ephemeral Sandbox Platform for AI Agents**.

---

## 1. What MCP Does in This Project

The Model Context Protocol (MCP) is an open standard that enables AI models and desktop assistants (such as Claude Desktop, Cursor, Continue, or custom orchestrators) to discover and execute capabilities exposed by external systems via a uniform interface.

In this platform, the MCP server exposes the hardened sandbox lifecycle and execution engine as standardized MCP tools. External MCP clients can:
- Allocate persistent, isolated sandbox sessions with custom Time-To-Live (TTL).
- Run arbitrary, untrusted Python code inside fresh, hardened, ephemeral Docker containers.
- Query historical execution results and stdout/stderr logs.
- Inspect sandbox status, remaining TTL, and execution counts.
- Destroy sandbox sessions idempotently.

---

## 2. Why MCP Does Not Replace the AI Agent

MCP and the internal AI Agent serve distinct architectural roles:

| Dimension | AI Agent (`SandboxAgent` / `POST /api/v1/agent/run`) | MCP Server (`app/mcp/server.py`) |
| :--- | :--- | :--- |
| **Role** | Autonomous problem solver | Capability provider / protocol server |
| **Intelligence** | Uses LLM (Gemini 3) to reason, loop, and decide *what* to run | Exposes *tools* to external LLMs / MCP clients |
| **Tool Calling** | Orchestrates tool loop internally based on user prompts | Receives tool calls from external clients via JSON-RPC |
| **Lifecycle** | Runs a multi-turn prompt $\rightarrow$ execute $\rightarrow$ evaluate loop | Stateless tool adapter backed by database transactions |

**Summary**: MCP enables external agents to use this sandbox platform as their execution engine; `SandboxAgent` is an autonomous agent built into the platform that uses those same tools internally.

---

## 3. Available MCP Tools

All MCP tools validate arguments against strict Pydantic schemas and return structured, deterministic JSON payloads:

### `create_sandbox`
- **Description**: Create a new isolated sandbox execution session with a configured Time-To-Live (TTL). Returns `sandbox_id` and expiration metadata for subsequent executions.
- **Parameters**:
  - `runtime` (*string*, default: `"python"`): Target execution runtime (allowed: `["python"]`).
  - `ttl_seconds` (*integer*, default: `300`, min: `10`, max: `86400`): Lifespan of sandbox session in seconds before expiration.

### `execute_code`
- **Description**: Run untrusted Python code inside a fresh, hardened, ephemeral container within an active sandbox session. Returns execution status, process exit code, stdout, stderr, and duration in milliseconds.
- **Parameters**:
  - `sandbox_id` (*string*, required): UUID of the active sandbox session.
  - `code` (*string*, required, length: `1`–`1,000,000`): Python code to execute inside the ephemeral container.
  - `timeout_seconds` (*float*, optional, min: `0.5`, max: `60.0`): Optional execution timeout override in seconds.

### `get_execution_result`
- **Description**: Retrieve historical execution outcome, captured logs (stdout/stderr), exit code, and timestamps for a previously executed job within a sandbox session.
- **Parameters**:
  - `sandbox_id` (*string*, required): UUID of the parent sandbox session.
  - `execution_id` (*string*, required): UUID of the execution job to inspect.

### `get_sandbox`
- **Description**: Check the lifecycle status, remaining TTL, resource limits, and total execution count of a sandbox session.
- **Parameters**:
  - `sandbox_id` (*string*, required): UUID of the sandbox session to query.

### `destroy_sandbox`
- **Description**: Idempotently terminate and tear down a sandbox session, freeing all associated resources and preventing further code execution.
- **Parameters**:
  - `sandbox_id` (*string*, required): UUID of the sandbox session to terminate and delete.

---

## 4. Architectural Delegation Flow

MCP is strictly a protocol translation layer. It contains **no Docker SDK code, no direct container operations, and no duplicated business logic**:

```
[MCP Client (Claude Desktop / Cursor / External Orchestrator)]
                             │
                  stdio JSON-RPC (MCP)
                             ▼
                    [app/mcp/server.py]
                    (FastMCP / MCPServer)
                             │
                    [app/mcp/tools.py]
              (Validates Pydantic schemas)
                             │
                    [app/agent/tools.py]
              (Thin application tool adapter)
                             │
             [SandboxLifecycleService]
        (Manages PostgreSQL state machine & TTL)
                             │
             [EphemeralSandboxEngine]
         (Enforces concurrency, timeouts & limits)
                             │
                     [Docker Engine]
     (Read-only rootfs, tmpfs /tmp, seccomp, drop caps, no-new-privileges)
```

### Security Isolation Guarantees
1. **Input Sandboxing**: MCP clients cannot inject custom Docker flags, arbitrary container images, host mounts, network configurations, or elevated Linux capabilities.
2. **Deterministic Hardening**: Every code run executes inside a fresh, non-reused container with:
   - Read-only root filesystem (`read_only=True`).
   - Ephemeral memory-only `/tmp` mount (`tmpfs`).
   - Dropped capabilities (`cap_drop=["ALL"]`).
   - Disabled network stack (`network_disabled=True`).
   - Enforced memory (`256m`), swap, CPU (`0.5`), and process limit (`pids_limit=32`).
3. **Database Scoping**: Each MCP tool call leases a scoped database session via `default_service_factory()` with guaranteed commit and cleanup.

---

## 5. Transport

The platform uses the **`stdio` (Standard Input / Output)** transport from the official Python MCP SDK (`mcp` 2.x).
- Standard input (`stdin`) and standard output (`stdout`) transport raw JSON-RPC protocol frames.
- Application logs are directed to standard error (`stderr`) to prevent stream pollution.
- Requires no open network ports or background HTTP listeners.

---

## 6. How to Start and Test the MCP Server

### Starting the MCP Server Manually
Run via `uv`:
```bash
uv run python -m app.mcp.server
```

### Configuring Claude Desktop (or Cursor)
Add the server definition to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ai-sandbox": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/ai-sandbox",
        "run",
        "python",
        "-m",
        "app.mcp.server"
      ],
      "env": {
        "SANDBOX_DATABASE_URL": "postgresql://sandbox_user:sandbox_password@localhost:5433/ai_sandbox_db"
      }
    }
  }
}
```

### Programmatic Discovery and Tool Testing
You can inspect registered tools using Python and the official MCP SDK:

```python
import asyncio
from app.mcp.server import create_mcp_server

async def discover():
    server = create_mcp_server()
    tools = await server.list_tools()
    for tool in tools:
        print(f"Tool: {tool.name}")
        print(f"Description: {tool.description}")
        print(f"Parameters: {list(tool.input_schema.get('properties', {}).keys())}\n")

asyncio.run(discover())
```

---

## 7. Automated Testing
Run the MCP test suite without requiring external API keys:

```bash
uv run pytest tests/mcp/ -v
```
