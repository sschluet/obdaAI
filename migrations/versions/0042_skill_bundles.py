"""Immutable private skill packages and exact revision manifests."""

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("skill_revisions") as batch:
        batch.add_column(sa.Column("bundle_sha256", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column("bundle_manifest", sa.Text(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM skill_revisions WHERE bundle_sha256 IS NOT NULL")
    ):
        raise RuntimeError("Preserve skill packages before downgrade")
    with op.batch_alter_table("skill_revisions") as batch:
        batch.drop_column("bundle_manifest")
        batch.drop_column("bundle_sha256")
