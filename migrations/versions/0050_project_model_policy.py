"""Add a provider-independent project preference without relabeling any context."""

import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("model_policy", sa.Text(), nullable=False,
                                        server_default="{}"))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM projects WHERE model_policy != '{}'")):
        raise RuntimeError("Project model preferences exist; preserve them before downgrade")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("model_policy")
