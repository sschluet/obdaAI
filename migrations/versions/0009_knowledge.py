"""Project-scoped sources, locators and canonical vault memory revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=160), primary_key=False, nullable=False),
        sa.Column("description", sa.Text(), primary_key=False, nullable=False),
        sa.Column("instructions", sa.Text(), primary_key=False, nullable=False),
        sa.Column("label", sa.String(length=20), primary_key=False, nullable=False),
        sa.Column("revision", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("archived", sa.Boolean(), primary_key=False, nullable=False),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("name", sa.String(length=240), primary_key=False, nullable=False),
        sa.Column("sha256", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("size", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("label", sa.String(length=20), primary_key=False, nullable=False),
        sa.Column("revision", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(length=20), primary_key=False, nullable=False),
        sa.Column("error", sa.String(length=240), primary_key=False, nullable=False),
        sa.Column("created", sa.Float(), primary_key=False, nullable=False),
    )
    op.create_index("ix_sources_project_id", "sources", ["project_id"])
    op.create_table(
        "source_chunks",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("sources.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("locator", sa.String(length=240), primary_key=False, nullable=False),
        sa.Column("content", sa.Text(), primary_key=False, nullable=False),
        sa.Column("structured", sa.Text(), primary_key=False, nullable=False),
    )
    op.create_index("ix_source_chunks_source_id", "source_chunks", ["source_id"])
    op.create_table(
        "memories",
        sa.Column("origin", sa.String(100), nullable=False),
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("path", sa.String(length=600), primary_key=False, nullable=False, unique=True),
        sa.Column("project_id", sa.String(length=36), primary_key=False, nullable=True),
        sa.Column("label", sa.String(length=20), primary_key=False, nullable=False),
        sa.Column("revision", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("sha256", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("content", sa.Text(), primary_key=False, nullable=False),
        sa.Column("base_content", sa.Text(), primary_key=False, nullable=False),
        sa.Column("conflict", sa.Text(), primary_key=False, nullable=False),
        sa.Column("deleted", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("writable", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("updated", sa.Float(), primary_key=False, nullable=False),
    )
    op.create_index("ix_memories_project_id", "memories", ["project_id"])
    op.create_table(
        "memory_revisions",
        sa.Column("memory_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("revision", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("content", sa.Text(), primary_key=False, nullable=False),
        sa.Column("sha256", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("created", sa.Float(), primary_key=False, nullable=False),
    )
    op.create_table(
        "research",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("query", sa.String(length=500), primary_key=False, nullable=False),
        sa.Column("results", sa.Text(), primary_key=False, nullable=False),
        sa.Column("created", sa.Float(), primary_key=False, nullable=False),
    )
    op.create_index("ix_research_project_id", "research", ["project_id"])
    op.add_column("conversations", sa.Column("project_id", sa.String(36), nullable=True))
    op.create_index("ix_conversations_project_id", "conversations", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_project_id", table_name="conversations")
    op.drop_column("conversations", "project_id")
    op.drop_table("research")
    op.drop_table("memory_revisions")
    op.drop_table("memories")
    op.drop_table("source_chunks")
    op.drop_table("sources")
    op.drop_table("projects")
