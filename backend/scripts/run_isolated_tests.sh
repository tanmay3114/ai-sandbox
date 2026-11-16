#!/usr/bin/env bash
# ==============================================================================
# AI Sandbox — Isolated Test Runner Script
# ==============================================================================
# Ensures pytest executes strictly within the isolated test environment.
# Passes all CLI arguments through to pytest.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Resolve .env.test location (backend/.env.test or root .env.test)
if [[ -f "$BACKEND_DIR/.env.test" ]]; then
    ENV_TEST_FILE="$BACKEND_DIR/.env.test"
elif [[ -f "$REPO_ROOT/.env.test" ]]; then
    ENV_TEST_FILE="$REPO_ROOT/.env.test"
else
    echo "ERROR: Test environment configuration file not found at $BACKEND_DIR/.env.test or $REPO_ROOT/.env.test" >&2
    exit 1
fi

# Resolve pytest executable
PYTEST_BIN=""
if [[ -x "$REPO_ROOT/.venv/bin/pytest" ]]; then
    PYTEST_BIN="$REPO_ROOT/.venv/bin/pytest"
elif [[ -x "$BACKEND_DIR/.venv/bin/pytest" ]]; then
    PYTEST_BIN="$BACKEND_DIR/.venv/bin/pytest"
elif [[ -x "$REPO_ROOT/venv/bin/pytest" ]]; then
    PYTEST_BIN="$REPO_ROOT/venv/bin/pytest"
elif [[ -x "$BACKEND_DIR/venv/bin/pytest" ]]; then
    PYTEST_BIN="$BACKEND_DIR/venv/bin/pytest"
elif command -v pytest >/dev/null 2>&1; then
    PYTEST_BIN="$(command -v pytest)"
else
    echo "ERROR: pytest executable not found in .venv, venv, or PATH" >&2
    exit 1
fi

# Export test environment variables
set -a
# shellcheck disable=SC1090
source "$ENV_TEST_FILE"
set +a

# Safety Invariant Check
if [[ "${SANDBOX_ENVIRONMENT:-}" != "test" ]] || \
   [[ "${COMPOSE_PROJECT_NAME:-}" != "ai-sandbox-test" ]] || \
   [[ "${SANDBOX_PROJECT_LABEL:-}" != "ai-sandbox-test" ]] || \
   [[ "${SANDBOX_DATABASE_URL:-}" != *"ai_sandbox_test"* ]] || \
   [[ "${SANDBOX_DATABASE_URL:-}" == *"ai_sandbox_db"* ]]; then
    echo "CRITICAL SAFETY ERROR: Unsafe test environment detected. Aborting." >&2
    exit 1
fi

echo "==> Running pytest in isolated test mode (PROJECT_LABEL=$SANDBOX_PROJECT_LABEL, DB=ai_sandbox_test)..."
exec "$PYTEST_BIN" "$@"
