"""Separate durable schedules; preserve immutable task manifests and receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_schedules",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("task_revision", sa.Integer(), nullable=False),
        sa.Column("control_revision", sa.Integer(), nullable=False),
        sa.Column("spec_sha256", sa.String(64), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("next_due", sa.Float(), nullable=True),
        sa.Column("error", sa.String(240), nullable=True),
    )
    op.create_table(
        "schedule_revisions",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "schedule_occurrences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("schedule_revision", sa.Integer(), nullable=False),
        sa.Column("due", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("task_runs.id"), unique=True),
        sa.Column("reason", sa.String(240), nullable=True),
        sa.Column("created", sa.Float(), nullable=False),
        sa.UniqueConstraint("task_id", "schedule_revision", "due"),
    )
    op.create_index("ix_schedule_occurrences_task_id", "schedule_occurrences", ["task_id"])
    op.create_table(
        "scheduler_pulse",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_tick", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if any(
        bind.scalar(sa.text(f"SELECT count(*) FROM {t}"))
        for t in ("task_schedules", "schedule_occurrences", "schedule_revisions")
    ):
        raise RuntimeError("Preserve schedules and execution history before downgrade")
    for table in (
        "scheduler_pulse",
        "schedule_occurrences",
        "schedule_revisions",
        "task_schedules",
    ):
        op.drop_table(table)
