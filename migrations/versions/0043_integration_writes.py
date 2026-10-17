"""Opt-in integration writes and durable pre-dispatch evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("integrations") as batch:
        batch.add_column(
            sa.Column("writes_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_table(
        "integration_write_audit",
        sa.Column("action_id", sa.String(36), primary_key=True),
        sa.Column("before_state", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "integration_write_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), unique=True, nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("integration_id", sa.String(36), nullable=False),
        sa.Column("integration_revision", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM integration_write_audit")):
        raise RuntimeError("Preserve integration write evidence before downgrade")
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM integration_write_drafts")):
        raise RuntimeError("Preserve integration drafts before downgrade")
    op.drop_table("integration_write_drafts")
    op.drop_table("integration_write_audit")
    with op.batch_alter_table("integrations") as batch:
        batch.drop_column("writes_enabled")
