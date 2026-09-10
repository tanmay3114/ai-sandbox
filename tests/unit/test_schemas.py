"""Unit tests for request and response schemas."""

import pytest
from pydantic import ValidationError

from app.sandbox.schemas import ExecutionRequest, ExecutionResult, ExecutionStatus


def test_valid_execution_request():
    req = ExecutionRequest(code="print('hi')", timeout_seconds=3.0)
    assert req.code == "print('hi')"
    assert req.timeout_seconds == 3.0


def test_execution_request_empty_code():
    with pytest.raises(ValidationError):
        ExecutionRequest(code="")

    with pytest.raises(ValidationError):
        ExecutionRequest(code="   \n\t  ")


def test_execution_request_invalid_timeout():
    with pytest.raises(ValidationError):
        ExecutionRequest(code="print(1)", timeout_seconds=0.2)

    with pytest.raises(ValidationError):
        ExecutionRequest(code="print(1)", timeout_seconds=100.0)


def test_valid_execution_result():
    res = ExecutionResult(
        sandbox_id="test-id",
        status=ExecutionStatus.COMPLETED,
        exit_code=0,
        stdout="hello\n",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=45,
    )
    assert res.status == ExecutionStatus.COMPLETED
    assert res.exit_code == 0
    assert res.stdout == "hello\n"
    assert not res.stdout_truncated
