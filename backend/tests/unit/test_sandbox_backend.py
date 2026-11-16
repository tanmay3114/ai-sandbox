"""Provider-neutral backend and cleanup ownership contract tests."""

from dataclasses import replace
from unittest.mock import MagicMock

import pytest
import requests

from app.api import dependencies
from app.core.exceptions import ResourceLimitError
from app.mcp import server as mcp_server
from app.sandbox.backend import SandboxBackend
from app.sandbox.docker_backend import DockerSandboxBackend
from app.sandbox.docker_client import cleanup_container_safely
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.policy import EffectiveSandboxPolicy
from app.sandbox.schemas import ExecutionRequest, ExecutionStatus
from app.sandbox.security import build_container_parameters
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


@pytest.fixture(autouse=True)
def verify_no_container_leak():
    """Unit tests in this module use mocks and do not interact with Docker."""
    yield


def test_docker_backend_satisfies_provider_neutral_contract(fast_settings):
    backend = DockerSandboxBackend(
        config=fast_settings,
        engine=EphemeralSandboxEngine(config=fast_settings, client=MagicMock()),
    )
    assert isinstance(backend, SandboxBackend)


def test_application_wiring_uses_the_process_shared_backend(monkeypatch):
    dependencies.get_sandbox_backend.cache_clear()
    dependencies.get_settings.cache_clear()
    db = MagicMock()
    monkeypatch.setattr(mcp_server, "SessionLocal", lambda: db)
    try:
        backend = dependencies.get_sandbox_backend()

        assert dependencies.get_sandbox_backend() is backend
        assert dependencies.get_sandbox_service().backend is backend
        assert SandboxLifecycleService(db=db, backend=backend).backend is backend
        with mcp_server.default_service_factory() as service:
            assert service.backend is backend
    finally:
        dependencies.get_sandbox_backend.cache_clear()
        dependencies.get_settings.cache_clear()


def test_lifecycle_service_requires_explicit_backend():
    with pytest.raises(TypeError):
        SandboxLifecycleService(db=MagicMock())  # type: ignore[call-arg]


def test_policy_is_immutable_and_rejects_missing_mandatory_control(fast_settings):
    policy = EffectiveSandboxPolicy.from_settings(fast_settings)
    weakened = replace(policy, network_disabled=False)

    with pytest.raises(ResourceLimitError):
        weakened.validate()


@pytest.mark.parametrize("identity", ["0", "0:0", "root", "", "10001", "10001:root", "x:y"])
def test_policy_rejects_non_approved_runtime_identities(fast_settings, identity):
    policy = EffectiveSandboxPolicy.from_settings(fast_settings)

    with pytest.raises(ResourceLimitError):
        replace(policy, run_as_user=identity).validate()


def test_policy_accepts_the_approved_non_root_identity(fast_settings):
    policy = EffectiveSandboxPolicy.from_settings(fast_settings)

    policy.validate()
    assert policy.run_as_user == "10001:10001"


def test_docker_parameters_reject_invalid_policy_before_container_creation(fast_settings):
    policy = replace(EffectiveSandboxPolicy.from_settings(fast_settings), run_as_user="0:0")

    with pytest.raises(ResourceLimitError):
        build_container_parameters("print('never runs')", "sandbox-a", fast_settings, policy)


def test_engine_rejects_invalid_policy_before_container_creation(fast_settings):
    client = MagicMock()
    engine = EphemeralSandboxEngine(config=fast_settings, client=client)
    policy = replace(EffectiveSandboxPolicy.from_settings(fast_settings), run_as_user="root")

    with pytest.raises(ResourceLimitError):
        engine.execute(ExecutionRequest(code="print('never runs')"), policy=policy)

    client.containers.run.assert_not_called()


def test_engine_uses_policy_timeout_for_wait_and_termination(fast_settings):
    client = MagicMock()
    container = MagicMock()
    container.id = "c" * 64
    container.attrs = {
        "Config": {
            "Labels": {
                "project": fast_settings.PROJECT_LABEL,
                "managed-by": fast_settings.MANAGED_BY_LABEL,
                "sandbox_id": "sandbox-a",
            }
        }
    }
    container.wait.side_effect = requests.exceptions.Timeout("timed out")
    container.logs.side_effect = [iter([b""]), iter([b""])]
    client.containers.run.return_value = container
    engine = EphemeralSandboxEngine(config=fast_settings, client=client)
    policy = replace(EffectiveSandboxPolicy.from_settings(fast_settings), timeout_seconds=0.5)

    result = engine.execute(
        ExecutionRequest(code="while True: pass", timeout_seconds=2.0),
        sandbox_id="sandbox-a",
        policy=policy,
    )

    container.wait.assert_called_once_with(timeout=0.5)
    container.kill.assert_called()
    assert result.status == ExecutionStatus.TIMED_OUT


def test_engine_honors_request_timeout_when_lower_than_policy(fast_settings):
    client = MagicMock()
    container = MagicMock()
    container.id = "e" * 64
    container.attrs = {
        "Config": {
            "Labels": {
                "project": fast_settings.PROJECT_LABEL,
                "managed-by": fast_settings.MANAGED_BY_LABEL,
                "sandbox_id": "sandbox-c",
            }
        }
    }
    container.wait.return_value = {"StatusCode": 0}
    container.logs.side_effect = [iter([b""]), iter([b""])]
    client.containers.run.return_value = container
    engine = EphemeralSandboxEngine(config=fast_settings, client=client)
    policy = replace(EffectiveSandboxPolicy.from_settings(fast_settings), timeout_seconds=1.0)

    engine.execute(
        ExecutionRequest(code="print('ok')", timeout_seconds=0.5),
        sandbox_id="sandbox-c",
        policy=policy,
    )

    container.wait.assert_called_once_with(timeout=0.5)


def test_engine_uses_policy_timeout_when_request_timeout_is_absent(fast_settings):
    client = MagicMock()
    container = MagicMock()
    container.id = "f" * 64
    container.attrs = {
        "Config": {
            "Labels": {
                "project": fast_settings.PROJECT_LABEL,
                "managed-by": fast_settings.MANAGED_BY_LABEL,
                "sandbox_id": "sandbox-d",
            }
        }
    }
    container.wait.side_effect = requests.exceptions.Timeout("timed out")
    container.logs.side_effect = [iter([b""]), iter([b""])]
    client.containers.run.return_value = container
    engine = EphemeralSandboxEngine(config=fast_settings, client=client)
    policy = replace(EffectiveSandboxPolicy.from_settings(fast_settings), timeout_seconds=0.5)

    result = engine.execute(
        ExecutionRequest(code="while True: pass"), sandbox_id="sandbox-d", policy=policy
    )

    container.wait.assert_called_once_with(timeout=0.5)
    container.kill.assert_called()
    assert result.status == ExecutionStatus.TIMED_OUT


def test_engine_uses_policy_timeout_when_request_timeout_is_none(fast_settings):
    """When ExecutionRequest.timeout_seconds is None, use EffectiveSandboxPolicy.timeout_seconds."""
    client = MagicMock()
    container = MagicMock()
    container.id = "g" * 64
    container.attrs = {
        "Config": {
            "Labels": {
                "project": fast_settings.PROJECT_LABEL,
                "managed-by": fast_settings.MANAGED_BY_LABEL,
                "sandbox_id": "sandbox-none-timeout",
            }
        }
    }
    container.wait.side_effect = requests.exceptions.Timeout("timed out")
    container.logs.side_effect = [iter([b""]), iter([b""])]
    client.containers.run.return_value = container

    # Normal engine configuration has fast_settings.TIMEOUT_SECONDS (2.0s).
    # Use a deliberately restrictive policy timeout that differs from normal engine configuration.
    restrictive_policy_timeout = 0.5
    assert restrictive_policy_timeout != fast_settings.TIMEOUT_SECONDS

    engine = EphemeralSandboxEngine(config=fast_settings, client=client)
    policy = replace(
        EffectiveSandboxPolicy.from_settings(fast_settings),
        timeout_seconds=restrictive_policy_timeout,
    )
    request = ExecutionRequest(code="while True: pass", timeout_seconds=None)
    assert request.timeout_seconds is None

    result = engine.execute(request, sandbox_id="sandbox-none-timeout", policy=policy)

    container.wait.assert_called_once_with(timeout=restrictive_policy_timeout)
    container.kill.assert_called()
    assert result.status == ExecutionStatus.TIMED_OUT


def test_engine_uses_separate_policy_output_limits(fast_settings):
    client = MagicMock()
    container = MagicMock()
    container.id = "d" * 64
    container.attrs = {
        "Config": {
            "Labels": {
                "project": fast_settings.PROJECT_LABEL,
                "managed-by": fast_settings.MANAGED_BY_LABEL,
                "sandbox_id": "sandbox-b",
            }
        }
    }
    container.wait.return_value = {"StatusCode": 0}
    container.logs.side_effect = [iter([b"abcdef"]), iter([b"uvwxyz"])]
    client.containers.run.return_value = container
    engine = EphemeralSandboxEngine(config=fast_settings, client=client)
    policy = replace(
        EffectiveSandboxPolicy.from_settings(fast_settings),
        max_stdout_bytes=3,
        max_stderr_bytes=4,
    )

    result = engine.execute(
        ExecutionRequest(code="print('output')"), sandbox_id="sandbox-b", policy=policy
    )

    assert result.stdout == "abc"
    assert result.stderr == "uvwx"
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


def test_cleanup_refuses_removal_when_ownership_reload_fails(fast_settings):
    container = MagicMock()
    container.id = "a" * 64
    container.reload.side_effect = RuntimeError("Docker API unavailable")

    assert (
        cleanup_container_safely(container, sandbox_id="sandbox-a", config=fast_settings) is False
    )
    container.kill.assert_not_called()
    container.remove.assert_not_called()


def test_cleanup_requires_exact_sandbox_ownership(fast_settings):
    container = MagicMock()
    container.id = "b" * 64
    container.attrs = {
        "Config": {
            "Labels": {
                "project": fast_settings.PROJECT_LABEL,
                "managed-by": fast_settings.MANAGED_BY_LABEL,
                "sandbox_id": "different-sandbox",
            }
        }
    }

    assert (
        cleanup_container_safely(container, sandbox_id="sandbox-a", config=fast_settings) is False
    )
    container.kill.assert_not_called()
    container.remove.assert_not_called()
