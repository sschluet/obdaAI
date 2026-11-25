"""Distinguish synthetic planner checks from basic answer/catalog checks."""

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_tests", sa.Column("mode", sa.String(20), nullable=False,
                                             server_default="model"))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM provider_tests WHERE mode != 'model'")):
        raise RuntimeError("Planner evidence exists; preserve it before downgrade")
    with op.batch_alter_table("provider_tests") as batch:
        batch.drop_column("mode")
