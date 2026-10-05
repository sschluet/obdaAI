"""Public chat research receipts remain distinct from every project scope."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("research") as batch:
        batch.alter_column("project_id", existing_type=sa.String(36), nullable=True)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM research WHERE project_id IS NULL")):
        raise RuntimeError("Global research exists; preserve/export it before schema downgrade")
    with op.batch_alter_table("research") as batch:
        batch.alter_column("project_id", existing_type=sa.String(36), nullable=False)
