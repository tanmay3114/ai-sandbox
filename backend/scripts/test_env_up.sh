#!/usr/bin/env bash
# ==============================================================================
# AI Sandbox — Safe Test Environment Startup Script
# ==============================================================================
# Starts only the isolated disposable test database and applies migrations.
# Will FAIL immediately if any setting points to development or production.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_TEST_FILE="$REPO_ROOT/.env.test"
COMPOSE_TEST_FILE="$REPO_ROOT/compose.test.yaml"

if [[ ! -f "$ENV_TEST_FILE" ]]; then
    echo "ERROR: Test environment configuration file not found at $ENV_TEST_FILE" >&2
    exit 1
fi

if [[ ! -f "$COMPOSE_TEST_FILE" ]]; then
    echo "ERROR: Test Compose file not found at $COMPOSE_TEST_FILE" >&2
    exit 1
fi

# Export test environment variables
set -a
# shellcheck disable=SC1090
source "$ENV_TEST_FILE"
set +a

# Strict Pre-flight Safety Validation
echo "==> Validating test environment isolation invariants..."

if [[ "${COMPOSE_PROJECT_NAME:-}" != "ai-sandbox-test" ]]; then
    echo "CRITICAL SAFETY ERROR: COMPOSE_PROJECT_NAME must be 'ai-sandbox-test', got '${COMPOSE_PROJECT_NAME:-}'" >&2
    exit 1
fi

if [[ "${POSTGRES_DB:-}" != "ai_sandbox_test" ]]; then
    echo "CRITICAL SAFETY ERROR: POSTGRES_DB must be 'ai_sandbox_test', got '${POSTGRES_DB:-}'" >&2
    exit 1
fi

if [[ "${SANDBOX_PROJECT_LABEL:-}" != "ai-sandbox-test" ]]; then
    echo "CRITICAL SAFETY ERROR: SANDBOX_PROJECT_LABEL must be 'ai-sandbox-test', got '${SANDBOX_PROJECT_LABEL:-}'" >&2
    exit 1
fi

if [[ "${SANDBOX_MANAGED_BY_LABEL:-}" != "ai-sandbox-platform-test" ]]; then
    echo "CRITICAL SAFETY ERROR: SANDBOX_MANAGED_BY_LABEL must be 'ai-sandbox-platform-test', got '${SANDBOX_MANAGED_BY_LABEL:-}'" >&2
    exit 1
fi

if [[ "${SANDBOX_ENVIRONMENT:-}" != "test" ]]; then
    echo "CRITICAL SAFETY ERROR: SANDBOX_ENVIRONMENT must be 'test', got '${SANDBOX_ENVIRONMENT:-}'" >&2
    exit 1
fi

if [[ "${SANDBOX_DATABASE_URL:-}" != *"ai_sandbox_test"* ]]; then
    echo "CRITICAL SAFETY ERROR: SANDBOX_DATABASE_URL must target 'ai_sandbox_test', got '${SANDBOX_DATABASE_URL:-}'" >&2
    exit 1
fi

if [[ "${SANDBOX_DATABASE_URL:-}" == *"ai_sandbox_db"* ]]; then
    echo "CRITICAL SAFETY ERROR: SANDBOX_DATABASE_URL matches development database 'ai_sandbox_db'!" >&2
    exit 1
fi

if [[ "${POSTGRES_PORT:-}" != "5439" ]]; then
    echo "CRITICAL SAFETY ERROR: POSTGRES_PORT must be 5439 to prevent conflict with dev, got '${POSTGRES_PORT:-}'" >&2
    exit 1
fi

# Verify Docker daemon availability
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon is not accessible. Please ensure Docker is running." >&2
    exit 1
fi

echo "==> Starting isolated test PostgreSQL container (project: ai-sandbox-test)..."
docker compose -p ai-sandbox-test -f "$COMPOSE_TEST_FILE" --env-file "$ENV_TEST_FILE" up -d --wait

echo "==> Applying Alembic migrations to disposable test database..."
SANDBOX_DATABASE_URL="$SANDBOX_DATABASE_URL" "$REPO_ROOT/venv/bin/alembic" upgrade head

echo "==> Isolated test environment is UP, migrated, and verified safe."
echo "    Database: $SANDBOX_DATABASE_URL"
echo "    Project Label: $SANDBOX_PROJECT_LABEL"
