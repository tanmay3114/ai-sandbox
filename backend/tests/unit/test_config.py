"""Unit tests for configuration validation and properties."""

import pytest
from pydantic import ValidationError

from app.core.config import SandboxSettings


def test_default_settings():
    settings = SandboxSettings()
    assert settings.MEMORY_LIMIT == "256m"
    assert settings.CPU_LIMIT == 0.5
    assert settings.nano_cpus == 500_000_000
    assert settings.TIMEOUT_SECONDS == 5.0
    assert settings.MAX_STDOUT_BYTES == 65536
    assert settings.PIDS_LIMIT == 32
    assert settings.GLOBAL_CONCURRENCY_LIMIT == 4
    assert settings.PROJECT_LABEL == "ai-sandbox"


def test_reject_floating_latest_image():
    with pytest.raises(ValidationError) as excinfo:
        SandboxSettings(BASE_IMAGE="python:latest")
    assert "Floating 'latest'" in str(excinfo.value)


def test_reject_invalid_cpu_limit():
    with pytest.raises(ValidationError):
        SandboxSettings(CPU_LIMIT=0.0)

    with pytest.raises(ValidationError):
        SandboxSettings(CPU_LIMIT=10.0)


def test_reject_invalid_timeout():
    with pytest.raises(ValidationError):
        SandboxSettings(TIMEOUT_SECONDS=0.1)

    with pytest.raises(ValidationError):
        SandboxSettings(TIMEOUT_SECONDS=120.0)


def test_custom_valid_settings():
    s = SandboxSettings(
        CPU_LIMIT=1.5,
        TIMEOUT_SECONDS=10.0,
        MAX_STDOUT_BYTES=131072,
        PIDS_LIMIT=64,
        BASE_IMAGE="python:3.12-slim",
    )
    assert s.nano_cpus == 1_500_000_000
    assert s.TIMEOUT_SECONDS == 10.0
    assert s.MAX_STDOUT_BYTES == 131072
    assert s.PIDS_LIMIT == 64
