"""Application-service tests using a Docker-independent fake backend."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import DockerEngineError
from app.models.sandbox import SandboxStatus, utc_now
from app.sandbox.schemas import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


class CapturingBackend:
    """Minimal backend fake proving lifecycle behavior does not require Docker."""

    def __init__(self, fail_cleanup_once: bool = False) -> None:
        self.requests: list[ExecutionRequest] = []
        self.cleanup_calls: list[str] = []
        self.fail_cleanup_once = fail_cleanup_once

    def execute(
        self, request: ExecutionRequest, *, sandbox_id: str | None = None
    ) -> ExecutionResult:
        self.requests.append(request)
        return ExecutionResult(
            sandbox_id=sandbox_id or "one-shot",
            status=ExecutionStatus.COMPLETED,
            exit_code=0,
            stdout="ok\n",
            stderr="",
            duration_ms=1,
        )

    def cleanup_sandbox(self, sandbox_id: str) -> None:
        self.cleanup_calls.append(sandbox_id)
        if self.fail_cleanup_once:
            self.fail_cleanup_once = False
            raise DockerEngineError("temporary cleanup failure")

    def check_health(self) -> None:
        return None


@pytest.mark.asyncio
async def test_lifecycle_passes_capped_timeout_to_backend(
    db_session: Session,
    fast_settings,
):
    backend = CapturingBackend()
    service = SandboxLifecycleService(db=db_session, backend=backend, config=fast_settings)
    sandbox = service.create_sandbox(ttl_seconds=60)

    await service.execute_code(sandbox.id, "print('ok')", timeout_seconds=60.0)

    assert backend.requests[0].timeout_seconds == fast_settings.TIMEOUT_SECONDS


def test_expired_sandbox_retries_cleanup_after_a_failure(db_session: Session, fast_settings):
    backend = CapturingBackend(fail_cleanup_once=True)
    service = SandboxLifecycleService(db=db_session, backend=backend, config=fast_settings)
    sandbox = service.create_sandbox(ttl_seconds=10)
    sandbox.expires_at = utc_now() - timedelta(seconds=1)
    db_session.commit()

    with pytest.raises(DockerEngineError):
        service.expire_sandbox(sandbox)

    db_session.refresh(sandbox)
    assert sandbox.status == SandboxStatus.EXPIRED

    service.expire_sandbox(sandbox)
    assert backend.cleanup_calls == [str(sandbox.id), str(sandbox.id)]
