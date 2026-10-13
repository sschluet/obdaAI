"""Bind every cloud conversation to one provider; preserve existing OR consent."""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversations",
        sa.Column("cloud_provider", sa.String(20), nullable=False, server_default="openrouter"),
    )
    op.add_column(
        "runs", sa.Column("cost_basis", sa.String(30), nullable=False, server_default="unknown")
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT (SELECT count(*) FROM conversations WHERE cloud_provider <> 'openrouter') "
            "+ (SELECT count(*) FROM provider_configs WHERE kind IN ('openai','anthropic'))"
        )
    ):
        raise RuntimeError("Preserve native provider consent before downgrade")
    op.drop_column("runs", "cost_basis")
    op.drop_column("conversations", "cloud_provider")
