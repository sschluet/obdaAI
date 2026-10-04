"""Persist event replay and reserve conversations while queued."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_events",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.drop_index("one_active_run_per_chat", table_name="runs")
    condition = sa.text("status IN ('queued', 'routing', 'streaming')")
    op.create_index(
        "one_active_run_per_chat",
        "runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=condition,
        sqlite_where=condition,
    )


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_index("one_active_run_per_chat", table_name="runs")
    condition = sa.text("status IN ('routing', 'streaming')")
    op.create_index(
        "one_active_run_per_chat",
        "runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=condition,
        sqlite_where=condition,
    )
