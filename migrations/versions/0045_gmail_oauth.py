"""Single-attempt Gmail OAuth state, PKCE and credential renewal evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gmail_oauth_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("integration_id", sa.String(36), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("cookie_hash", sa.String(64), nullable=True),
        sa.Column("encrypted_verifier", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.Column("finished", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_gmail_oauth_attempts_integration_id", "gmail_oauth_attempts", ["integration_id"]
    )

    op.create_index(
        "one_gmail_refresh_per_revision",
        "gmail_oauth_attempts",
        ["integration_id", "profile_revision"],
        unique=True,
        sqlite_where=sa.text("operation = 'refresh' AND status = 'dispatching'"),
        postgresql_where=sa.text("operation = 'refresh' AND status = 'dispatching'"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM gmail_oauth_attempts")):
        raise RuntimeError("Preserve OAuth and renewal evidence before downgrade")
    op.drop_index("one_gmail_refresh_per_revision", "gmail_oauth_attempts")
    op.drop_index("ix_gmail_oauth_attempts_integration_id", "gmail_oauth_attempts")
    op.drop_table("gmail_oauth_attempts")
