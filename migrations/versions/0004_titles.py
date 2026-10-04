"""One durable local title attempt per conversation; preserve existing manual titles."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("title_status", sa.String(20), nullable=False, server_default="idle"),
    )
    op.execute("UPDATE conversations SET title_status = 'manual' WHERE manual_title = true")


def downgrade() -> None:
    op.drop_column("conversations", "title_status")
