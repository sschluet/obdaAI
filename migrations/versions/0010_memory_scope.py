"""Explicit global vault chat without implicit cross-project memory mixing."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("memory_scope", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "memory_scope")
