# AI Sandbox — Frontend & Backend-For-Frontend (BFF)

Production-ready web application for the **AI Sandbox Platform**, providing secure browser-to-sandbox lifecycle management, persistent workspace browsing/editing, autonomous agent task orchestration, comprehensive audit history, and static performance benchmarks.

---

## 1. Architecture Overview

Browser clients connect strictly to the **same-origin Backend-For-Frontend (BFF)** proxy. The browser never connects directly to FastAPI and never has access to backend secrets.

```
React Browser Client
       │
       │ (Same-Origin Relative /api/* Calls)
       ▼
Server-Side BFF Proxy (Node.js)
  - Enforces strict route/method allowlist
  - Strips client-supplied x-api-key & host headers
  - Injects SANDBOX_API_KEY from server environment
  - Accommodates 300s timeout for agent orchestration
       │
       │ (Authenticated Internal Requests with X-API-Key)
       ▼
FastAPI Sandbox Backend (:8000)
  ├── Docker Execution Backend (cgroup / unprivileged user)
  ├── QEMU MicroVM Backend (Apple Silicon HVF / arm64)
  └── PostgreSQL Database (:5432)
```

---

## 2. Environment Variables

The server-side BFF requires the following environment variables (stored on the server; **never** exposed to Vite client bundles with `VITE_`):

| Variable | Description | Default |
| :--- | :--- | :--- |
| `FASTAPI_URL` or `SANDBOX_BACKEND_URL` | Upstream FastAPI backend URL | `http://127.0.0.1:8000` |
| `SANDBOX_API_KEY` or `API_KEY` | Server-side shared secret key for FastAPI authentication | `""` |
| `PORT` | Listening port for standalone production BFF server | `3000` |

---

## 3. Getting Started

### Development Mode (with integrated Vite BFF middleware)

```bash
cd frontend
npm install
npm run dev
```
The Vite development server runs at `http://localhost:5173`. Incoming requests to `/api/*`, `/health`, and `/ready` are intercepted by the `bffPlugin()` middleware and forwarded to `http://127.0.0.1:8000` with the server-side API key injected.

### Production Build & Standalone BFF Server

```bash
cd frontend
npm run build
npm run bff:start
```
Runs a standalone HTTP server at `http://localhost:3000` that serves production frontend assets (`dist/`) with SPA fallback and proxies allowlisted API requests to the FastAPI backend.

---

## 4. Testing & Validation

```bash
cd frontend

# TypeScript check
npx tsc -b

# Linter check
npm run lint

# Production build
npm run build

# Integration tests (BFF allowlist & benchmark invariants)
npm test
```

---

## 5. Key Product Flows & Operational Details

### A. Sandbox Lifecycle
- **Create**: Creates a logical sandbox record with user-defined TTL (10s to 86,400s).
- **Inspect**: Displays status (`running`, `executing`, `expired`, `destroyed`), configured runtime (`python`), creation date, and remaining TTL.
- **Destroy**: Idempotently issues `DELETE /api/v1/sandboxes/{sandbox_id}` after confirmation.

### B. Persistent Workspace
- Mounted into execution containers at `/workspace`.
- Browse root and subdirectories with breadcrumb navigation.
- In-place text editor for Python scripts, configuration files, and text assets.
- Base64 binary detector: binary files are opened in safe read-only mode to prevent corruption.
- Quota indicator: displays live file counts against the 1,000 files limit and storage usage against the 50 MiB quota.

### C. Autonomous Agent Orchestration
- **Synchronous Execution**: Agent task submission (`POST /api/v1/sandboxes/{sandbox_id}/agent/tasks`) is **request-bound and synchronous**. It does NOT use SSE or WebSockets. The BFF provides a 300-second upstream timeout.
- **Connection Recovery**: If the client connection drops or times out, the task continues asynchronously on the backend. The UI detects connection interruptions and polls `GET /api/v1/sandboxes/{sandbox_id}/agent/tasks/{task_id}` until reaching terminal state (`completed`, `failed`, `cancelled`, `timed_out`).
- **Explicit Cancellation**: Cancellation calls `POST /api/v1/sandboxes/{sandbox_id}/agent/tasks/{task_id}/cancel`. It does not rely on `AbortController`.
- **Zero Chain-of-Thought**: Hidden internal reasoning is never displayed. Only structured tool audit logs (tool name, status, timestamp, arguments) and final natural-language explanations (`result_summary`) are rendered.

### D. Audit History
- Unified timeline at `/dashboard/history` combining ephemeral code execution history and agent task orchestrations.
- Client-side search and filtering by category (`All`, `Code Executions`, `Agent Tasks`).
- Expandable detail drawers showing exit codes, durations, stdout, stderr, iterations, and error types.

### E. Audited Performance Benchmarks
- Accessible at `/dashboard/benchmarks`.
- Rendered from static, audited benchmark data (`bench_audited_20261110_103626`, 106 raw runs total: 53 Docker, 53 QEMU).
- **No live benchmark REST API is called or simulated.**
- Prominently displays the memory measurement boundary caveat: Docker reflects container cgroup RSS (`memory.current`), whereas QEMU reflects host hypervisor process RSS (including the 256 MB guest physical RAM reservation).
