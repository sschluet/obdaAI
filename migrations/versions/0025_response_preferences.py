"""Revisioned typed response style preferences, separate from permissions."""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "response_preferences",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "response_preference_revisions",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("overrides", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM response_preferences")
    ) or op.get_bind().scalar(sa.text("SELECT count(*) FROM response_preference_revisions")):
        raise RuntimeError("Preserve response preferences and revision history before downgrade")
    op.drop_table("response_preference_revisions")
    op.drop_table("response_preferences")
