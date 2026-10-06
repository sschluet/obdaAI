"""Durable local document-ready events and bounded task subscriptions."""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_ready_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created", sa.Float(), nullable=False),
        sa.UniqueConstraint("source_id", "source_sha256"),
    )
    op.create_index("ix_source_ready_events_project_id", "source_ready_events", ["project_id"])
    # Existing ready originals are a baseline, never new automatic triggers. This
    # also preserves their identity across later explicit parser revisions.
    op.execute(
        sa.text(
            "INSERT INTO source_ready_events "
            "(project_id, source_id, source_revision, source_sha256, created, baseline) "
            "SELECT project_id, id, revision, sha256, created, true FROM sources "
            "WHERE status = 'ready' AND label = 'LOCAL_ONLY'"
        )
    )
    op.add_column(
        "task_schedules",
        sa.Column("event_cursor", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "task_event_occurrences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("schedule_revision", sa.Integer(), nullable=False),
        sa.Column(
            "event_id", sa.Integer(), sa.ForeignKey("source_ready_events.id"), nullable=False
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("task_runs.id"), unique=True),
        sa.Column("reason", sa.String(240)),
        sa.Column("created", sa.Float(), nullable=False),
        sa.UniqueConstraint("task_id", "schedule_revision", "event_id"),
    )
    op.create_index("ix_task_event_occurrences_task_id", "task_event_occurrences", ["task_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM source_ready_events")):
        raise RuntimeError("Preserve document events and task receipts before downgrade")
    op.drop_table("task_event_occurrences")
    op.drop_column("task_schedules", "event_cursor")
    op.drop_table("source_ready_events")
