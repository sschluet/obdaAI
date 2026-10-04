"""Persistent login, conversations, messages and runs."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("csrf", sa.String(64), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("manual_title", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("cloud_allowed", sa.Boolean(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("label", sa.String(20), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("error", sa.String(240)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("started", sa.Float(), nullable=False),
        sa.Column("finished", sa.Float()),
        sa.Column("router_seconds", sa.Float()),
        sa.Column("first_content_seconds", sa.Float()),
        sa.Column("cost", sa.Float()),
    )
    op.create_index("ix_runs_conversation_id", "runs", ["conversation_id"])
    condition = sa.text("status IN ('routing', 'streaming')")
    op.create_index(
        "one_active_run_per_chat",
        "runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=condition,
        sqlite_where=condition,
    )


def downgrade() -> None:
    for table in ("runs", "messages", "conversations", "login_sessions"):
        op.drop_table(table)
