"""Bounded task authority and durable action linkage."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def active_index(states: str) -> None:
    op.drop_index("one_active_task_run", table_name="task_runs")
    op.create_index(
        "one_active_task_run",
        "task_runs",
        ["task_id"],
        unique=True,
        sqlite_where=sa.text(states),
        postgresql_where=sa.text(states),
    )


def upgrade() -> None:
    op.create_table(
        "task_write_grants",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("task_revision", sa.Integer(), nullable=False),
        sa.Column("control_revision", sa.Integer(), nullable=False),
        sa.Column("spec_sha256", sa.String(64), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "task_write_grant_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_index("ix_task_write_grant_events_task_id", "task_write_grant_events", ["task_id"])
    op.create_table(
        "task_action_links",
        sa.Column("action_id", sa.String(36), sa.ForeignKey("action_intents.id"), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("task_runs.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint("run_id", "sequence"),
    )
    op.create_index("ix_task_action_links_run_id", "task_action_links", ["run_id"])
    active_index("status IN ('queued', 'running', 'awaiting_approval')")


def downgrade() -> None:
    if any(
        op.get_bind().scalar(sa.text(f"SELECT count(*) FROM {t}"))
        for t in ("task_write_grants", "task_action_links", "task_write_grant_events")
    ):
        raise RuntimeError("Preserve task authority audit before downgrade")
    active_index("status IN ('queued', 'running')")
    op.drop_table("task_action_links")
    op.drop_table("task_write_grant_events")
    op.drop_table("task_write_grants")
