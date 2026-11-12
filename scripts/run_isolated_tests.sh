#!/usr/bin/env bash
# ==============================================================================
# AI Sandbox — Isolated Test Runner Script
# ==============================================================================
# Ensures pytest executes strictly within the isolated test environment.
# Passes all CLI arguments through to pytest.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_TEST_FILE="$REPO_ROOT/.env.test"

if [[ ! -f "$ENV_TEST_FILE" ]]; then
    echo "ERROR: Test environment configuration file not found at $ENV_TEST_FILE" >&2
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
exec "$REPO_ROOT/venv/bin/pytest" "$@"
