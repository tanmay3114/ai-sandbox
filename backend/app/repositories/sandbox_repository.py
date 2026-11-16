"""Repository for Sandbox database persistence."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.models.sandbox import Sandbox, SandboxStatus, utc_now


class SandboxRepository:
    """Encapsulates PostgreSQL database operations for Sandbox entities."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        runtime: str,
        ttl_seconds: int,
        resource_config: dict[str, Any],
        sandbox_id: uuid.UUID | None = None,
    ) -> Sandbox:
        """Create and persist a new Sandbox entity in RUNNING state."""
        now = utc_now()
        expires_at = now + timedelta(seconds=ttl_seconds)

        sandbox = Sandbox(
            id=sandbox_id or uuid.uuid4(),
            status=SandboxStatus.RUNNING,
            runtime=runtime,
            ttl_seconds=ttl_seconds,
            created_at=now,
            expires_at=expires_at,
            resource_config=resource_config,
        )
        self.db.add(sandbox)
        self.db.commit()
        self.db.refresh(sandbox)
        return sandbox

    def get_by_id(self, sandbox_id: uuid.UUID) -> Sandbox | None:
        """Fetch a Sandbox by its primary key UUID."""
        stmt = select(Sandbox).where(Sandbox.id == sandbox_id)
        return self.db.scalars(stmt).first()

    def get_by_id_for_update(self, sandbox_id: uuid.UUID) -> Sandbox | None:
        """Fetch a Sandbox with a row-level lock (FOR UPDATE) to prevent race conditions."""
        stmt = select(Sandbox).where(Sandbox.id == sandbox_id).with_for_update()
        return self.db.scalars(stmt).first()

    def update_status(self, sandbox: Sandbox, target_status: SandboxStatus) -> Sandbox:
        """Transition sandbox to new status and persist."""
        previous_status = sandbox.status
        previous_destroyed_at = sandbox.destroyed_at
        sandbox.transition_to(target_status)
        try:
            self.db.commit()
        except Exception:
            sandbox.status = previous_status
            sandbox.destroyed_at = previous_destroyed_at
            self.db.rollback()
            raise
        self.db.refresh(sandbox)
        return sandbox

    def list_sandboxes(self, limit: int = 100, offset: int = 0) -> list[Sandbox]:
        """List sandboxes ordered by creation time descending."""
        stmt = (
            select(Sandbox)
            .options(selectinload(Sandbox.executions))
            .order_by(Sandbox.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt).all())

    def claim_for_execution(self, sandbox_id: uuid.UUID) -> Sandbox | None:
        """Atomically move a ready, non-expired sandbox to EXECUTING.

        The conditional update prevents two concurrent requests from both
        observing RUNNING and submitting work for the same logical sandbox,
        and prevents claiming a sandbox whose TTL has already elapsed.
        """
        now = utc_now()
        stmt = (
            update(Sandbox)
            .where(
                Sandbox.id == sandbox_id,
                Sandbox.status == SandboxStatus.RUNNING,
                Sandbox.expires_at > now,
            )
            .values(status=SandboxStatus.EXECUTING, updated_at=now)
        )
        try:
            result = self.db.execute(stmt)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        if result.rowcount != 1:
            return None
        return self.get_by_id(sandbox_id)

    def release_execution_claim(self, sandbox_id: uuid.UUID) -> Sandbox | None:
        """Conditionally transition an EXECUTING sandbox back to RUNNING if still active.

        Does not overwrite DESTROYING, DESTROYED, or EXPIRED states if a concurrent
        lifecycle termination occurred during execution.
        """
        now = utc_now()
        stmt = (
            update(Sandbox)
            .where(
                Sandbox.id == sandbox_id,
                Sandbox.status == SandboxStatus.EXECUTING,
                Sandbox.expires_at > now,
            )
            .values(status=SandboxStatus.RUNNING, updated_at=now)
        )
        try:
            self.db.execute(stmt)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.get_by_id(sandbox_id)

    def get_expired_active(self, now: datetime | None = None, limit: int = 50) -> list[Sandbox]:
        """Find sandboxes whose TTL has passed and are not DESTROYED or DESTROYING."""
        check_time = now or utc_now()
        stmt = (
            select(Sandbox)
            .where(
                Sandbox.status.not_in([SandboxStatus.DESTROYED, SandboxStatus.DESTROYING]),
                Sandbox.expires_at <= check_time,
            )
            .order_by(Sandbox.expires_at.asc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_stale_active(self, cutoff: datetime) -> list[Sandbox]:
        """Find sandboxes stuck in transient/executing states older than cutoff for recovery."""
        stmt = (
            select(Sandbox)
            .where(
                Sandbox.status.in_([SandboxStatus.EXECUTING, SandboxStatus.DESTROYING]),
                Sandbox.updated_at <= cutoff,
            )
            .order_by(Sandbox.updated_at.asc())
        )
        return list(self.db.scalars(stmt).all())
