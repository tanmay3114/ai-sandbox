"""add recovery and cancellation fields to agent_tasks

Revision ID: d5d885c9b3ef
Revises: c5d885c9a2ef
Create Date: 2026-11-10 22:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5d885c9b3ef"
down_revision: str | Sequence[str] | None = "c5d885c9a2ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: add recovery and cancellation tracking fields."""
    op.add_column(
        "agent_tasks",
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_tasks",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_tasks",
        sa.Column("worker_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "agent_tasks",
        sa.Column("interruption_reason", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_agent_tasks_cancellation_requested_at"),
        "agent_tasks",
        ["cancellation_requested_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_agent_tasks_cancellation_requested_at"),
        table_name="agent_tasks",
    )
    op.drop_column("agent_tasks", "interruption_reason")
    op.drop_column("agent_tasks", "worker_id")
    op.drop_column("agent_tasks", "claimed_at")
    op.drop_column("agent_tasks", "cancellation_requested_at")
