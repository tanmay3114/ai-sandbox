# Cloud-Based Ephemeral Sandbox Platform for AI Agents

A modular-monolith FastAPI service that records logical sandbox sessions and
execution jobs in PostgreSQL, then runs each submitted Python program in a new
hardened Docker container.

## Architecture

```text
FastAPI API -> services -> repositories / sandbox engine -> PostgreSQL / Docker
```

`Sandbox` is a persistent logical session with a TTL. `ExecutionJob` is a
persistent record belonging to that sandbox. Each job receives a fresh,
ephemeral container; files written during one execution do not persist to the
next execution.

## Prerequisites

- Python 3.12+
- Docker Engine or Docker Desktop running, with permission to use its socket
- The trusted runtime image available locally (Docker will pull
  the digest-pinned Python 3.12 image configured in `SandboxSettings` when needed)

## Local setup

```bash
git clone <your-private-repository-url>
cd ai-sandbox
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env` and replace `change_me` with your own local PostgreSQL password.
Do not commit `.env`.

Start the local PostgreSQL database:

```bash
docker compose up -d db
```

Apply the schema migration and start the API:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

Open Swagger UI at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
Liveness and readiness endpoints are available at `/health` and `/ready`.

Set `SANDBOX_ENVIRONMENT=staging` or `production` only with a long,
non-committed `SANDBOX_API_KEY`. Every `/api/v1` request must then include the
same value in `X-API-Key`. The unauthenticated `/health` and `/ready` probes
remain available for local infrastructure monitoring.

## Development checks

The test suite needs both the configured PostgreSQL database and Docker.

```bash
pytest -q
ruff check .
alembic check
```

## API lifecycle

- `POST /api/v1/sandboxes` creates a persistent logical sandbox with a TTL.
- `GET /api/v1/sandboxes/{sandbox_id}` returns lifecycle information.
- `POST /api/v1/sandboxes/{sandbox_id}/execute` creates and records a job.
- `DELETE /api/v1/sandboxes/{sandbox_id}` idempotently tears down the logical
  sandbox and any matching project-owned runtime resources.
- `POST /api/v1/sandboxes/execute` remains the one-shot, backward-compatible
  execution endpoint.
- `POST /api/v1/sandboxes/{sandbox_id}/agent/tasks` creates and executes an autonomous
  agent task with bounded reasoning, tool calling, and iterative error recovery.
- `GET /api/v1/sandboxes/{sandbox_id}/agent/tasks` lists all tasks for a sandbox.
- `GET /api/v1/sandboxes/{sandbox_id}/agent/tasks/{task_id}` retrieves detailed task status.
- `POST /api/v1/sandboxes/{sandbox_id}/agent/tasks/{task_id}/cancel` durably cancels an
  active or pending task with immediate side-effect cessation.
- `GET /api/v1/sandboxes/{sandbox_id}/agent/tasks/{task_id}/executions` inspects all
  code execution jobs triggered by the task.

Sandbox TTL and execution timeout are intentionally different: TTL controls
how long the logical sandbox may be used, while execution timeout limits one
container run. A timed-out job does not destroy an otherwise active logical
sandbox; an expired sandbox cannot accept new jobs.

## Durable agent recovery and lifecycle

Agent tasks persist state in PostgreSQL (`AgentTask`), establishing database
records as the authoritative source of truth across process crashes and restarts:
- **Startup Reconciliation**: Interrupted `RUNNING` tasks are automatically marked
  `FAILED` with `interruption_reason="PROCESS_RESTARTED"` without blind replays.
- **Durable Cancellation**: Cancellation requests persist `cancellation_requested_at`
  in PostgreSQL before completing, halting execution before subsequent tool calls.
- **Atomic Worker Claims**: Tasks transition from `PENDING` to `RUNNING` through
  conditional atomic updates, preventing duplicate execution across workers.

## Sandbox security model

Every execution container is configured with:

- `network_mode="none"`, no host mounts, and no Docker socket mount
- a read-only root filesystem and a size-bounded, `noexec` `/tmp` tmpfs
- non-root execution as UID/GID `10001:10001`
- all Linux capabilities dropped and `no-new-privileges` enabled
- strict CPU, memory, swap, PID, timeout, stdout, and stderr limits
- a fixed trusted runtime image; API clients cannot choose arbitrary images
- project-scoped labels and deterministic cleanup in `finally` paths

Submitted code is hostile input. Do not weaken these controls to troubleshoot a
local setup issue.

## EC2 demonstration deployment

The production topology is intentionally small: one EC2 instance runs the API
and a private PostgreSQL service. The API is bound to `127.0.0.1:8000`; place a
TLS reverse proxy in front of it only after API-key access is verified. Docker
socket access belongs only to the trusted API container, never to MCP clients
or execution containers.

```bash
cp .env.production.example .env.production
# Edit generated passwords/keys and set the Docker group ID for this host.
docker compose -f compose.production.yaml --env-file .env.production up -d --build db
docker compose -f compose.production.yaml --env-file .env.production run --rm api alembic upgrade head
docker compose -f compose.production.yaml --env-file .env.production up -d api
curl -H "X-API-Key: $SANDBOX_API_KEY" http://127.0.0.1:8000/health
```

On Ubuntu EC2, set `DOCKER_GID` to `stat -c '%g' /var/run/docker.sock` before
starting the stack. The API container remains non-root and receives only that
supplementary group; its Docker socket access is still equivalent to high host
privilege and must remain limited to this trusted backend.

Before a public demonstration, restrict the EC2 security group to SSH from
your IP and HTTPS only, keep PostgreSQL unexposed, configure a domain and TLS
proxy, and rehearse rollback with the prior image tag. The mounted Docker
socket is a residual host-level risk; API authentication and private exposure
are mandatory compensating controls for this single-instance academic setup.

## Database migrations

Alembic obtains its URL from the same application setting. `alembic.ini`'s
generic template is overridden by `alembic/env.py` before migrations run.
Current schema:

```bash
alembic current
```

## Before sharing changes

Keep `.env`, virtual environments, caches, certificates, and keys untracked.
Review staged content before committing:

```bash
git add .
git diff --cached --name-only
git diff --cached --check
```
