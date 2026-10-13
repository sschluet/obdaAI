"""Immutable artifact specifications and reviewable offline output versions."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])
    op.create_table(
        "artifact_revisions",
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("artifacts.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("request_key", sa.String(36), unique=True, nullable=False),
        sa.Column("spec", sa.Text(), nullable=False),
        sa.Column("spec_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("manifest", sa.Text(), nullable=False),
        sa.Column("error", sa.String(240), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("started", sa.Float(), nullable=True),
        sa.Column("accepted", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM artifacts")):
        raise RuntimeError("Preserve artifact version records before downgrade")
    op.drop_table("artifact_revisions")
    op.drop_table("artifacts")
