#!/usr/bin/env bash
# ==============================================================================
# AI Sandbox — Safe Test Environment Teardown Script
# ==============================================================================
# Destroys only resources owned by the dedicated test Compose project (ai-sandbox-test).
# Will NEVER delete development volumes, development containers, or other projects.
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
if [[ "${COMPOSE_PROJECT_NAME:-}" != "ai-sandbox-test" ]]; then
    echo "CRITICAL SAFETY ERROR: Refusing teardown! COMPOSE_PROJECT_NAME must be 'ai-sandbox-test', got '${COMPOSE_PROJECT_NAME:-}'" >&2
    exit 1
fi

if [[ "${SANDBOX_PROJECT_LABEL:-}" != "ai-sandbox-test" ]]; then
    echo "CRITICAL SAFETY ERROR: Refusing teardown! SANDBOX_PROJECT_LABEL must be 'ai-sandbox-test', got '${SANDBOX_PROJECT_LABEL:-}'" >&2
    exit 1
fi

echo "==> Tearing down isolated test Docker Compose project (ai-sandbox-test)..."
docker compose -p ai-sandbox-test -f "$COMPOSE_TEST_FILE" --env-file "$ENV_TEST_FILE" down -v --remove-orphans

echo "==> Checking for any remaining test-specific sandbox containers..."
# Targeted cleanup: ONLY containers with label project=ai-sandbox-test AND managed-by=ai-sandbox-platform-test
STRAY_TEST_CONTAINERS=$(docker ps -aq \
    --filter "label=project=ai-sandbox-test" \
    --filter "label=managed-by=ai-sandbox-platform-test" 2>/dev/null || true)

if [[ -n "$STRAY_TEST_CONTAINERS" ]]; then
    echo "==> Removing stray test execution containers: $STRAY_TEST_CONTAINERS"
    docker rm -f $STRAY_TEST_CONTAINERS
else
    echo "==> No stray test execution containers found."
fi

echo "==> Test environment teardown complete. Development resources remain untouched."
