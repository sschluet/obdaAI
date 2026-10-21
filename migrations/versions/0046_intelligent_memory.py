"""Extend the canonical memory store without moving or rewriting existing content."""

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("storage", sa.String(length=16), nullable=False, server_default="vault"),
    )
    op.add_column(
        "memories",
        sa.Column("owner_id", sa.String(length=36), nullable=False, server_default="owner"),
    )
    op.add_column(
        "memories",
        sa.Column("category", sa.String(length=24), nullable=False, server_default="knowledge"),
    )
    op.add_column(
        "memories",
        sa.Column("fact_type", sa.String(length=16), nullable=False, server_default="fact"),
    )
    op.add_column(
        "memories",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
    )
    op.add_column(
        "memories", sa.Column("subject", sa.String(length=120), nullable=False, server_default="")
    )
    op.add_column(
        "memories", sa.Column("predicate", sa.String(length=120), nullable=False, server_default="")
    )
    op.add_column(
        "memories", sa.Column("confidence", sa.Float(), nullable=False, server_default="1")
    )
    op.add_column(
        "memories",
        sa.Column("sensitivity", sa.String(length=16), nullable=False, server_default="private"),
    )
    op.add_column(
        "memories", sa.Column("cloud_providers", sa.Text(), nullable=False, server_default="[]")
    )
    op.add_column("memories", sa.Column("valid_from", sa.Float(), nullable=True))
    op.add_column("memories", sa.Column("valid_until", sa.Float(), nullable=True))
    op.add_column("memories", sa.Column("source_message_id", sa.String(length=36), nullable=True))
    op.add_column("memories", sa.Column("source_message_revision", sa.Integer(), nullable=True))
    op.add_column(
        "memories", sa.Column("source_conversation_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "memories",
        sa.Column("source_sha256", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column("memories", sa.Column("supersedes_id", sa.String(length=36), nullable=True))
    op.create_index("ix_memories_source_message_id", "memories", ["source_message_id"])
    op.create_index(
        "ix_memories_retrieval", "memories", ["owner_id", "storage", "status", "project_id"]
    )
    op.create_table(
        "memory_settings",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("extraction_enabled", sa.Boolean(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
    )
    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("source_message_id", sa.String(length=36), nullable=False),
        sa.Column("source_message_revision", sa.Integer(), nullable=False),
        sa.Column("source_conversation_id", sa.String(length=36), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=False),
        sa.Column("quote_end", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("fact_type", sa.String(length=24), nullable=False),
        sa.Column("subject", sa.String(length=80), nullable=False),
        sa.Column("predicate", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sensitivity", sa.String(length=24), nullable=False),
        sa.Column("explicit_correction", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=True),
        sa.Column("created", sa.Float(), nullable=False),
        sa.UniqueConstraint(
            "source_message_id", "source_message_revision", "quote_start", "quote_end", "predicate"
        ),
    )
    op.create_index(
        "ix_memory_candidates_source_message_id", "memory_candidates", ["source_message_id"]
    )
    op.create_table(
        "memory_learning_jobs",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("source_message_id", sa.String(length=36), nullable=False),
        sa.Column("source_message_revision", sa.Integer(), nullable=False),
        sa.Column("source_conversation_id", sa.String(length=36), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("settings_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error", sa.String(length=80), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("finished", sa.Float(), nullable=True),
        sa.UniqueConstraint("source_message_id", "source_message_revision", "extractor_version"),
    )
    op.create_index(
        "ix_memory_learning_jobs_source_message_id", "memory_learning_jobs", ["source_message_id"]
    )
    op.create_index("ix_memory_learning_jobs_status", "memory_learning_jobs", ["status"])
    op.create_table(
        "memory_embeddings",
        sa.Column(
            "memory_id",
            sa.String(length=36),
            sa.ForeignKey("memories.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=240), nullable=False),
        sa.Column("config_sha256", sa.String(length=64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.Text(), nullable=False),
        sa.Column("updated", sa.Float(), nullable=False),
    )
    op.create_table(
        "conversation_summaries",
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_snapshot", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=20), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("updated", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "memory_settings",
        "memory_candidates",
        "memory_learning_jobs",
        "memory_embeddings",
        "conversation_summaries",
    ):
        if bind.scalar(sa.text("SELECT count(*) FROM " + table)):
            raise RuntimeError("Preserve memory state before downgrade")
    if bind.scalar(sa.text("SELECT count(*) FROM memories WHERE storage <> 'vault'")):
        raise RuntimeError("Preserve app-native memories before downgrade")
    op.drop_table("conversation_summaries")
    op.drop_table("memory_embeddings")
    op.drop_table("memory_learning_jobs")
    op.drop_table("memory_candidates")
    op.drop_table("memory_settings")
    op.drop_index("ix_memories_retrieval", "memories")
    op.drop_index("ix_memories_source_message_id", "memories")
    op.drop_column("memories", "supersedes_id")
    op.drop_column("memories", "source_sha256")
    op.drop_column("memories", "source_conversation_id")
    op.drop_column("memories", "source_message_revision")
    op.drop_column("memories", "source_message_id")
    op.drop_column("memories", "valid_until")
    op.drop_column("memories", "valid_from")
    op.drop_column("memories", "cloud_providers")
    op.drop_column("memories", "sensitivity")
    op.drop_column("memories", "confidence")
    op.drop_column("memories", "predicate")
    op.drop_column("memories", "subject")
    op.drop_column("memories", "status")
    op.drop_column("memories", "fact_type")
    op.drop_column("memories", "category")
    op.drop_column("memories", "owner_id")
    op.drop_column("memories", "storage")
