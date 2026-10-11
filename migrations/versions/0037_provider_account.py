"""Separate encrypted read-only OpenRouter account credential."""

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_account_credentials",
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("provider_configs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    configured = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM provider_account_credentials WHERE encrypted_secret IS NOT NULL"
        )
    )
    if configured:
        raise RuntimeError(
            "Configured account credentials must be preserved; clear explicitly first"
        )
    op.drop_table("provider_account_credentials")
