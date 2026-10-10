"""Archive skill library entries without deleting immutable revision history."""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skills", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM skills WHERE archived")):
        raise RuntimeError("Preserve archived skill decisions before downgrade")
    op.drop_column("skills", "archived")
