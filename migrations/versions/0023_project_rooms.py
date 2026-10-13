"""Project room website snapshots and separate external knowledge sources."""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects", sa.Column("kind", sa.String(20), nullable=False, server_default="project")
    )
    op.add_column(
        "sources", sa.Column("origin_url", sa.String(2048), nullable=False, server_default="")
    )
    op.add_column("sources", sa.Column("web_request_id", sa.String(36), nullable=True))
    op.create_index("ix_sources_web_request_id", "sources", ["web_request_id"], unique=True)
    op.create_table(
        "knowledge_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("address", sa.String(1000), nullable=False),
        sa.Column("target_ref", sa.String(100), nullable=False),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False, unique=True
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("indexed", sa.Integer(), nullable=False),
        sa.Column("last_indexed", sa.Float()),
        sa.Column("error", sa.String(240), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("knowledge_connections.id"),
            nullable=False,
        ),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id"), nullable=False),
        sa.UniqueConstraint("connection_id", "path"),
    )
    op.create_index(
        "ix_knowledge_documents_connection_id", "knowledge_documents", ["connection_id"]
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM knowledge_connections")
    ) or op.get_bind().scalar(sa.text("SELECT count(*) FROM sources WHERE origin_url <> ''")):
        raise RuntimeError("Preserve knowledge sources and website snapshots before downgrade")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_connections")
    op.drop_index("ix_sources_web_request_id", table_name="sources")
    op.drop_column("sources", "web_request_id")
    op.drop_column("sources", "origin_url")
    op.drop_column("projects", "kind")
