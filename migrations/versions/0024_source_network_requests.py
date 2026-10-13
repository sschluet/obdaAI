"""Short-lived owner-confirmed source-only network leases."""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_network_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
    )


def downgrade():
    op.drop_table("source_network_requests")
