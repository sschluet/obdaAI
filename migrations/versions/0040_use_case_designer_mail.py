"""Reviewed Use Case design dialogs and explicit single-attempt mail delivery."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_default",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("integration_id", sa.String(36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "use_case_mail_previews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("use_case_runs.id"), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
    )
    op.create_index("ix_use_case_mail_previews_run_id", "use_case_mail_previews", ["run_id"])
    op.create_table(
        "use_case_mail_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "preview_id", sa.String(36), sa.ForeignKey("use_case_mail_previews.id"), nullable=False
        ),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message_id", sa.String(160), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.UniqueConstraint("preview_id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_table(
        "use_case_designers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("model_mode", sa.String(20), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_table(
        "use_case_designer_turns",
        sa.Column(
            "designer_id", sa.String(36), sa.ForeignKey("use_case_designers.id"), primary_key=True
        ),
        sa.Column("turn", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column(
            "execution_run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False, unique=True
        ),
        sa.UniqueConstraint("designer_id", "request_id"),
    )


def downgrade() -> None:
    db = op.get_bind()
    for document in db.scalars(sa.text("SELECT spec FROM use_case_revisions")):
        value = json.loads(document)
        if any(
            key in value
            for key in ["integration_inputs", "integration_processing", "output_integration_id"]
        ):
            raise RuntimeError("Preserve stage-aware Use Case definitions before downgrade")
    for name in ["mail_default", "use_case_mail_previews", "use_case_designers"]:
        if db.scalar(sa.text("SELECT count(*) FROM " + name)):
            raise RuntimeError("Preserve configured mail and designer data before downgrade")
    if db.scalar(sa.text("SELECT count(*) FROM conversations WHERE purpose='use_case_designer'")):
        raise RuntimeError("Preserve designer conversations before downgrade")
    for name in [
        "use_case_designer_turns",
        "use_case_designers",
        "use_case_mail_deliveries",
        "use_case_mail_previews",
        "mail_default",
    ]:
        op.drop_table(name)
