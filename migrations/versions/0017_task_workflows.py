"""Revision-bound n8n task workflows and durable dispatch intents."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("task_revision", sa.Integer(), nullable=False),
        sa.Column("control_revision", sa.Integer(), nullable=False),
        sa.Column("spec_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("graph", sa.Text(), nullable=True),
        sa.Column("remote_id", sa.String(128), nullable=True),
        sa.Column("remote_version", sa.String(36), nullable=True),
        sa.Column("header_id", sa.String(128), nullable=True),
        sa.Column("created", sa.Float(), nullable=False),
        sa.UniqueConstraint("task_id", "task_revision"),
    )
    op.create_index("ix_workflow_bindings_task_id", "workflow_bindings", ["task_id"])
    op.create_table(
        "workflow_dispatches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "binding_id", sa.String(36), sa.ForeignKey("workflow_bindings.id"), nullable=False
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("control_revision", sa.Integer(), nullable=False),
        sa.Column(
            "run_id", sa.String(36), sa.ForeignKey("task_runs.id"), unique=True, nullable=True
        ),
        sa.Column("execution_id", sa.String(32), nullable=True),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_index("ix_workflow_dispatches_binding_id", "workflow_dispatches", ["binding_id"])
    op.create_index(
        "one_pending_workflow_dispatch",
        "workflow_dispatches",
        ["binding_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('prepared', 'uncertain')"),
        postgresql_where=sa.text("status IN ('prepared', 'uncertain')"),
    )


def downgrade() -> None:
    if any(
        op.get_bind().scalar(sa.text(f"SELECT count(*) FROM {t}"))
        for t in ("workflow_bindings", "workflow_dispatches")
    ):
        raise RuntimeError("Preserve workflow audit before downgrade")
    op.drop_table("workflow_dispatches")
    op.drop_table("workflow_bindings")
