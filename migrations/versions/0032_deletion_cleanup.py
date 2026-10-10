"""Durable content-free deletion cleanup across fixed worker mount boundaries."""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def event_foreign_key() -> str:
    for constraint in sa.inspect(op.get_bind()).get_foreign_keys("task_event_occurrences"):
        if constraint["constrained_columns"] == ["event_id"]:
            return constraint["name"] or "fk_task_event_occurrences_event_id_source_ready_events"
    raise RuntimeError("Source event foreign key missing; inspect schema before migration")


def alter_event_reference(*, detach: bool) -> None:
    constraint_name = event_foreign_key()
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("task_event_occurrences", naming_convention=naming) as batch:
        batch.drop_constraint(constraint_name, type_="foreignkey")
        batch.alter_column("event_id", existing_type=sa.Integer(), nullable=detach)
        if detach:
            batch.add_column(
                sa.Column("deleted_event_snapshot", sa.Text(), nullable=False, server_default="")
            )
        else:
            batch.drop_column("deleted_event_snapshot")
        batch.create_foreign_key(
            "task_event_occurrences_event_id_fkey",
            "source_ready_events",
            ["event_id"],
            ["id"],
            ondelete="SET NULL" if detach else None,
        )


def upgrade() -> None:
    alter_event_reference(detach=True)
    op.create_table(
        "deletion_cleanup",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("manifest", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(160), nullable=False),
        sa.Column("source_done", sa.Boolean(), nullable=False),
        sa.Column("artifact_done", sa.Boolean(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("finished", sa.Float(), nullable=True),
    )
    op.create_index("ix_deletion_cleanup_status", "deletion_cleanup", ["status"])


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM deletion_cleanup WHERE status != 'completed'")
    ):
        raise RuntimeError("Finish deletion cleanup before downgrade")
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM task_event_occurrences "
            "WHERE event_id IS NULL OR deleted_event_snapshot != ''"
        )
    ):
        raise RuntimeError("Preserve detached source event audit before downgrade")
    alter_event_reference(detach=False)
    op.drop_table("deletion_cleanup")
