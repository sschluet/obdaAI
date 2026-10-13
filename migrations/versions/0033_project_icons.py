"""Configurable project icon metadata with a default for existing projects."""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects", sa.Column("icon", sa.String(40), nullable=False, server_default="folder")
    )


def downgrade() -> None:
    op.drop_column("projects", "icon")
