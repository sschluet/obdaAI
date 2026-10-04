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
    op.execute("INSERT INTO login_throttle (id, window, attempts) VALUES (1, 0, 0)")


def downgrade() -> None:
    op.drop_table("login_throttle")
