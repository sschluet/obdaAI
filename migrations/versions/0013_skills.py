"""Immutable portable skill revisions and explicit per-chat selection."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("skill_selection", sa.Text(), nullable=True))
    op.create_table(
        "skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("trusted_sha256", sa.String(64), nullable=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=True),
    )
    op.create_table(
        "skill_revisions",
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("skills.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM skills")):
        raise RuntimeError("Preserve immutable skill audit before downgrade")
    op.drop_table("skill_revisions")
    op.drop_table("skills")
    op.drop_column("conversations", "skill_selection")
