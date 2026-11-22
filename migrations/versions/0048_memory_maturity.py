"""Additive provenance-backed summary segments and bounded learning retry metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_learning_jobs",
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_table(
        "conversation_summary_segments",
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("updated", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_conversation_summary_segments_conversation_id",
        "conversation_summary_segments",
        ["conversation_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM conversation_summary_segments")) or bind.scalar(
        sa.text("SELECT count(*) FROM memory_learning_jobs WHERE attempts > 1")
    ):
        raise RuntimeError("Memory summary/retry evidence exists; preserve it before downgrade")
    op.drop_index(
        "ix_conversation_summary_segments_conversation_id",
        table_name="conversation_summary_segments",
    )
    op.drop_table("conversation_summary_segments")
    with op.batch_alter_table("memory_learning_jobs") as batch:
        batch.drop_column("attempts")
