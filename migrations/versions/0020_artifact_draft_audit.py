"""Preserve authenticated local model provenance on each artifact version."""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "artifact_revisions",
        sa.Column("draft_metadata", sa.Text(), nullable=False, server_default=""),
    )

    op.add_column(
        "artifact_revisions",
        sa.Column("chat_metadata", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM artifact_revisions "
            "WHERE draft_metadata <> '' OR chat_metadata <> ''"
        )
    ):
        raise RuntimeError("Preserve artifact model audit before downgrade")
    op.drop_column("artifact_revisions", "draft_metadata")

    op.drop_column("artifact_revisions", "chat_metadata")
