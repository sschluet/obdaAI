"""Private artifacts owned by an ordinary conversation or a project."""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("artifacts") as batch:
        batch.alter_column("project_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("conversation_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_artifacts_conversation_id", "conversations", ["conversation_id"], ["id"]
        )
        batch.create_index("ix_artifacts_conversation_id", ["conversation_id"])
        batch.create_check_constraint(
            "artifact_owner_scope",
            "(project_id IS NOT NULL AND conversation_id IS NULL) OR "
            "(project_id IS NULL AND conversation_id IS NOT NULL)",
        )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM artifacts WHERE conversation_id IS NOT NULL")
    ):
        raise RuntimeError("Preserve conversation artifacts before downgrade")
    with op.batch_alter_table("artifacts") as batch:
        batch.drop_constraint("artifact_owner_scope", type_="check")
        batch.drop_index("ix_artifacts_conversation_id")
        batch.drop_constraint("fk_artifacts_conversation_id", type_="foreignkey")
        batch.drop_column("conversation_id")
        batch.alter_column("project_id", existing_type=sa.String(36), nullable=False)
