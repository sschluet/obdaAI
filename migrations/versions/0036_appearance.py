"""Private workspace display preferences, separate from model context."""

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appearance_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("app_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("avatar_data_url", sa.Text(), nullable=True),
        sa.Column("density", sa.Text(), nullable=False),
        sa.Column("accent", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("appearance_settings")
