"""Manual read tasks, immutable specs and atomic durable read receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("control_revision", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "task_revisions",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("spec", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "task_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("task_revision", sa.Integer(), nullable=False),
        sa.Column("control_revision", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(36), unique=True, nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(240), nullable=True),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("finished", sa.Float(), nullable=True),
    )
    op.create_index("ix_task_runs_task_id", "task_runs", ["task_id"])
    op.create_index(
        "one_active_task_run",
        "task_runs",
        ["task_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_table(
        "task_steps",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("task_runs.id"), primary_key=True),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("tool_id", sa.String(80), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("finished", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM tasks")):
        raise RuntimeError("Preserve task specifications and receipts before downgrade")
    for table in ("task_steps", "task_runs", "task_revisions", "tasks"):
        op.drop_table(table)
