"""Versioned project forms and immutable local result snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "use_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_index("ix_use_cases_project_id", "use_cases", ["project_id"])
    op.create_table(
        "use_case_revisions",
        sa.Column("use_case_id", sa.String(36), sa.ForeignKey("use_cases.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("spec", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
    )
    op.create_table(
        "use_case_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("use_case_id", sa.String(36), sa.ForeignKey("use_cases.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.UniqueConstraint("use_case_id", "request_id"),
    )
    op.create_index("ix_use_case_runs_use_case_id", "use_case_runs", ["use_case_id"])


def downgrade() -> None:
    op.drop_table("use_case_runs")
    op.drop_table("use_case_revisions")
    op.drop_table("use_cases")
