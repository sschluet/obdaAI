"""Persistent single-user credential and bounded password-change attempts."""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("password_hash", sa.String(256), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("changed", sa.Float(), nullable=True),
        sa.CheckConstraint("id = 1", name="account_credential_singleton"),
    )
    op.bulk_insert(
        sa.table(
            "account_credentials",
            sa.column("id", sa.Integer()),
            sa.column("revision", sa.Integer()),
        ),
        [{"id": 1, "revision": 0}],
    )
    op.bulk_insert(
        sa.table(
            "login_throttle",
            sa.column("id", sa.Integer()),
            sa.column("window", sa.Float()),
            sa.column("attempts", sa.Integer()),
        ),
        [{"id": 2, "window": 0, "attempts": 0}],
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM account_credentials "
            "WHERE password_hash IS NOT NULL OR revision > 0"
        )
    ):
        raise RuntimeError("Preserve the configured login credential before downgrade")
    op.execute(sa.text("DELETE FROM login_throttle WHERE id = 2"))
    op.drop_table("account_credentials")
