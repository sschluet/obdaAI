"""Persist routing preferences and actual run decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "routing_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(16), nullable=False),
        sa.Column("complex_research_cloud", sa.Boolean(), nullable=False),
        sa.CheckConstraint("id = 1 AND revision >= 0", name="routing_settings_singleton"),
        sa.CheckConstraint(
            "strategy IN ('balanced', 'local_first', 'cloud_first')",
            name="routing_settings_strategy",
        ),
    )
    op.bulk_insert(
        table, [{"id": 1, "revision": 0, "strategy": "balanced", "complex_research_cloud": True}]
    )
    op.add_column(
        "runs", sa.Column("routing_trace", sa.Text(), nullable=False, server_default="{}")
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM routing_settings WHERE revision > 0")):
        raise RuntimeError("Preserve configured routing settings before downgrade")
    op.drop_column("runs", "routing_trace")
    op.drop_table("routing_settings")
