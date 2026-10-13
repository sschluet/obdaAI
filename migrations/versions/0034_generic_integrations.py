"""Typed integration drafts and owner-scoped selection bindings."""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("last_check", sa.Text(), nullable=True),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "integration_bindings",
        sa.Column("scope", sa.String(20), primary_key=True),
        sa.Column("owner_id", sa.String(36), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("integration_ids", sa.Text(), nullable=False),
        sa.Column("selection_mode", sa.String(20), nullable=False),
    )


def downgrade() -> None:
    connection = op.get_bind()
    for name in ("integrations", "integration_bindings"):
        if connection.execute(sa.text("SELECT count(*) FROM " + name)).scalar():
            raise RuntimeError("Integration data must be explicitly removed before downgrade")
    op.drop_table("integration_bindings")
    op.drop_table("integrations")
