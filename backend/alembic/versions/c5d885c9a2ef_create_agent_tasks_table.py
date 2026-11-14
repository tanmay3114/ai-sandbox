"""create agent_tasks table

Revision ID: c5d885c9a2ef
Revises: 3190bf3b73be
Create Date: 2026-11-10 20:56:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d885c9a2ef"
down_revision: str | Sequence[str] | None = "3190bf3b73be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sandbox_id", sa.Uuid(), nullable=False),
        sa.Column("task_description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("iterations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column(
            "tool_history",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["sandbox_id"], ["sandboxes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_tasks_created_at"), "agent_tasks", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_agent_tasks_sandbox_id"), "agent_tasks", ["sandbox_id"], unique=False
    )
    op.create_index(op.f("ix_agent_tasks_status"), "agent_tasks", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_agent_tasks_status"), table_name="agent_tasks")
    op.drop_index(op.f("ix_agent_tasks_sandbox_id"), table_name="agent_tasks")
    op.drop_index(op.f("ix_agent_tasks_created_at"), table_name="agent_tasks")
    op.drop_table("agent_tasks")
