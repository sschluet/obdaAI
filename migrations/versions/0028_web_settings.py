"""Persist user research options without changing approved endpoint configuration."""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "web_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("safe_search", sa.Integer(), nullable=False),
        sa.Column("max_results", sa.Integer(), nullable=False),
        sa.Column("timeout", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1 AND revision >= 0", name="web_settings_singleton"),
        sa.CheckConstraint("language IN ('all', 'de', 'en')", name="web_settings_language"),
        sa.CheckConstraint(
            "safe_search BETWEEN 0 AND 2 AND max_results BETWEEN 1 AND 8 "
            "AND timeout BETWEEN 5 AND 30",
            name="web_settings_limits",
        ),
    )
    op.bulk_insert(
        table,
        [
            {
                "id": 1,
                "revision": 0,
                "enabled": True,
                "language": "all",
                "safe_search": 1,
                "max_results": 8,
                "timeout": 15,
            }
        ],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM web_settings WHERE revision > 0")):
        raise RuntimeError("Preserve configured web settings before downgrade")
    op.drop_table("web_settings")
