"""Revision-bound chat branches, idempotent requests and German full-text indexes."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "messages", sa.Column("active", sa.Boolean(), nullable=False, server_default="true")
    )
    op.add_column("runs", sa.Column("request_key", sa.String(36)))
    op.add_column(
        "runs", sa.Column("request_digest", sa.String(64), nullable=False, server_default="")
    )
    op.create_index("ix_runs_request_key", "runs", ["request_key"], unique=True)
    op.add_column(
        "runs", sa.Column("context_snapshot", sa.Text(), nullable=False, server_default="")
    )
    if op.get_bind().dialect.name == "postgresql":
        for table, column in [("messages", "content"), ("conversations", "title")]:
            op.execute(
                f"CREATE INDEX ix_{table}_fts ON {table} USING gin "
                f"(to_tsvector('german', {column}))"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("messages", "conversations"):
            op.drop_index(f"ix_{table}_fts", table_name=table)
    op.drop_column("runs", "context_snapshot")
    op.drop_index("ix_runs_request_key", table_name="runs")
    op.drop_column("runs", "request_key")
    op.drop_column("runs", "request_digest")
    op.drop_column("messages", "active")
    op.drop_column("messages", "revision")
