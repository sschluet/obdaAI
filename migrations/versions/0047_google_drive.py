"""Single-attempt Google Drive OAuth state, PKCE and credential renewal evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_drive_oauth_attempts",
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
        "ix_google_drive_oauth_attempts_integration_id",
        "google_drive_oauth_attempts",
        ["integration_id"],
    )

    op.create_index(
        "one_google_drive_refresh_per_revision",
        "google_drive_oauth_attempts",
        ["integration_id", "profile_revision"],
        unique=True,
        sqlite_where=sa.text("operation = 'refresh' AND status = 'dispatching'"),
        postgresql_where=sa.text("operation = 'refresh' AND status = 'dispatching'"),
    )

    op.create_table(
        "google_drive_transfers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("integration_id", sa.String(36), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("remote_id", sa.String(256), nullable=False),
        sa.Column("folder_id", sa.String(256), nullable=False),
        sa.Column("artifact_id", sa.String(36), nullable=True),
        sa.Column("artifact_revision", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_md5", sa.String(32), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("mime_type", sa.String(160), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("updated", sa.Float(), nullable=False),
        sa.Column("error", sa.String(80), nullable=False),
    )
    op.create_index(
        "ix_google_drive_transfers_integration_id", "google_drive_transfers", ["integration_id"]
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM integrations WHERE kind='google_drive'")):
        raise RuntimeError("Preserve Google Drive connection configuration before downgrade")
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM google_drive_oauth_attempts")
    ) or op.get_bind().scalar(sa.text("SELECT count(*) FROM google_drive_transfers")):
        raise RuntimeError("Preserve OAuth and renewal evidence before downgrade")
    op.drop_index("ix_google_drive_transfers_integration_id", "google_drive_transfers")
    op.drop_table("google_drive_transfers")
    op.drop_index("one_google_drive_refresh_per_revision", "google_drive_oauth_attempts")
    op.drop_index("ix_google_drive_oauth_attempts_integration_id", "google_drive_oauth_attempts")
    op.drop_table("google_drive_oauth_attempts")
