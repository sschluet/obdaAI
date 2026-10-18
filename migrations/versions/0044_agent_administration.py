"""Administration rules and durable agent loops; disabled until explicitly configured."""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("agent_job_id", sa.String(36), nullable=True))
    op.create_table(
        "agent_policies",
        sa.Column("integration_id", sa.String(36), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("rules", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "agent_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), unique=True, nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("model_conversation_id", sa.String(36), nullable=False),
        sa.Column("task_run_id", sa.String(36), unique=True, nullable=True),
        sa.Column("task_revision", sa.Integer(), nullable=True),
        sa.Column("control_revision", sa.Integer(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("bindings", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("research_allowed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("max_effects", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("finished", sa.Float(), nullable=True),
    )
    op.create_index(
        "one_active_agent_per_scope",
        "agent_jobs",
        ["scope", "owner_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued','running','awaiting_approval','awaiting_input')"),
        postgresql_where=sa.text(
            "status IN ('queued','running','awaiting_approval','awaiting_input')"
        ),
    )
    op.create_table(
        "agent_steps",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("model_run_id", sa.String(36), nullable=True),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "agent_policy_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("integration_id", sa.String(36), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_agent_policy_events_integration_id", "agent_policy_events", ["integration_id"]
    )


def downgrade() -> None:
    for table in ("agent_steps", "agent_jobs", "agent_policy_events", "agent_policies"):
        if op.get_bind().scalar(sa.text("SELECT count(*) FROM " + table)):
            raise RuntimeError("Preserve agent authority and execution evidence before downgrade")
    for table in ("agent_steps", "agent_jobs", "agent_policy_events", "agent_policies"):
        op.drop_table(table)
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("agent_job_id")
