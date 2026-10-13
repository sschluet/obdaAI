"""Versioned MCP connection inventory; no remote tool grants."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "tool_connection_revisions",
        sa.Column(
            "connection_id", sa.String(36), sa.ForeignKey("tool_connections.id"), primary_key=True
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "tool_connection_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id", sa.String(36), sa.ForeignKey("tool_connections.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_tool_connection_checks_connection_id", "tool_connection_checks", ["connection_id"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    if any(
        bind.scalar(sa.text(f"SELECT count(*) FROM {t}"))
        for t in ("tool_connections", "tool_connection_revisions", "tool_connection_checks")
    ):
        raise RuntimeError("Preserve tool connection audit before downgrade")
    for table in ("tool_connection_checks", "tool_connection_revisions", "tool_connections"):
        op.drop_table(table)
