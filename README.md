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
  `python:3.12-slim` when needed)

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

Sandbox TTL and execution timeout are intentionally different: TTL controls
how long the logical sandbox may be used, while execution timeout limits one
container run. A timed-out job does not destroy an otherwise active logical
sandbox; an expired sandbox cannot accept new jobs.

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
