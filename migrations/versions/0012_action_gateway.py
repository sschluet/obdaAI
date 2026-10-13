"""Action proposals, explicit grants, final pause boundary and local receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.execute(sa.text("INSERT INTO action_policy (id, paused, revision) VALUES (1, true, 1)"))
    op.create_table(
        "action_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_key", sa.String(36), nullable=False, unique=True),
        sa.Column("tool_id", sa.String(80), nullable=False),
        sa.Column("tool_revision", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.Text(), nullable=False),
        sa.Column("parameters_sha256", sa.String(64), nullable=False),
        sa.Column("label", sa.String(20), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "action_grants",
        sa.Column("action_id", sa.String(36), sa.ForeignKey("action_intents.id"), primary_key=True),
        sa.Column("parameters_sha256", sa.String(64), nullable=False),
        sa.Column("tool_revision", sa.Integer(), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "action_receipts",
        sa.Column("action_id", sa.String(36), sa.ForeignKey("action_intents.id"), primary_key=True),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("finished", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM action_intents")):
        raise RuntimeError(
            "Preserve action audit before downgrade; nonempty history cannot be dropped"
        )
    for name in ("action_receipts", "action_grants", "action_intents", "action_policy"):
        op.drop_table(name)
