"""One persistent login-rate window across both API processes and restarts."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_throttle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("window", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "login_throttle",
            sa.column("id", sa.Integer()),
            sa.column("window", sa.Float()),
            sa.column("attempts", sa.Integer()),
        ),
        [{"id": 1, "window": 0, "attempts": 0}],
    )


def downgrade() -> None:
    op.drop_table("login_throttle")
