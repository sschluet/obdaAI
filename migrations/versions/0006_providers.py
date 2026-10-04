"""Revisioned provider settings, encrypted credentials and conservative budget ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("encrypted_secret", sa.Text()),
    )
    op.create_index(
        "one_default_provider_per_kind",
        "provider_configs",
        ["kind"],
        unique=True,
        sqlite_where=sa.text("is_default = true"),
        postgresql_where=sa.text("is_default = true"),
    )
    op.create_table(
        "provider_tests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "provider_revisions",
        sa.Column("provider_id", sa.String(36), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("ceiling", sa.Float(), nullable=False),
        sa.Column("measured", sa.Float()),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_index("ix_budget_reservations_provider_id", "budget_reservations", ["provider_id"])
    op.create_index("ix_budget_reservations_month", "budget_reservations", ["month"])
    op.add_column("runs", sa.Column("model", sa.String(240), nullable=False, server_default=""))
    op.add_column("runs", sa.Column("provider_revision", sa.Integer()))
    op.add_column("runs", sa.Column("capabilities", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("runs", sa.Column("cost_estimate", sa.Float()))


def downgrade() -> None:
    for column in ("model", "provider_revision", "capabilities", "cost_estimate"):
        op.drop_column("runs", column)
    for table in (
        "budget_reservations",
        "provider_tests",
        "provider_revisions",
        "provider_configs",
    ):
        op.drop_table(table)
