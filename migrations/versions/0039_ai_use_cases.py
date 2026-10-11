"""Durable AI use cases, private immutable uploads and dialog turns."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations", sa.Column("purpose", sa.String(20), nullable=False, server_default="chat")
    )
    with op.batch_alter_table("use_case_runs") as batch:
        batch.add_column(sa.Column("execution_run_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_use_case_run_execution", "runs", ["execution_run_id"], ["id"])
    op.create_table(
        "use_case_uploads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("use_case_id", sa.String(36), sa.ForeignKey("use_cases.id"), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("extracted", sa.Text(), nullable=False),
        sa.Column("receipt", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
    )
    op.create_index("ix_use_case_uploads_use_case_id", "use_case_uploads", ["use_case_id"])
    op.create_table(
        "use_case_dialogues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("use_case_id", sa.String(36), sa.ForeignKey("use_cases.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column(
            "conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("spec", sa.Text(), nullable=False),
        sa.Column("model_mode", sa.String(20), nullable=False),
        sa.Column("initial_values", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.UniqueConstraint("use_case_id", "request_id"),
    )
    op.create_index("ix_use_case_dialogues_use_case_id", "use_case_dialogues", ["use_case_id"])
    op.create_table(
        "use_case_dialogue_turns",
        sa.Column(
            "dialogue_id", sa.String(36), sa.ForeignKey("use_case_dialogues.id"), primary_key=True
        ),
        sa.Column("turn", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("execution_run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.UniqueConstraint("dialogue_id", "request_id"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if sa.inspect(connection).has_table("use_case_revisions"):
        for document in connection.scalars(sa.text("SELECT spec FROM use_case_revisions")):
            try:
                value = json.loads(document)
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict) and value.get("execution_kind") == "ai":
                raise RuntimeError("Preserve AI use-case definitions before downgrade")
    if connection.scalar(sa.text("SELECT count(*) FROM conversations WHERE purpose='use_case'")):
        raise RuntimeError("Preserve AI use-case conversations before downgrade")
    if (
        connection.scalar(sa.text("SELECT count(*) FROM use_case_uploads"))
        or connection.scalar(sa.text("SELECT count(*) FROM use_case_dialogues"))
        or connection.scalar(
            sa.text("SELECT count(*) FROM use_case_runs WHERE execution_run_id IS NOT NULL")
        )
    ):
        raise RuntimeError("Preserve AI use-case data before downgrade")
    op.drop_table("use_case_dialogue_turns")
    op.drop_table("use_case_dialogues")
    op.drop_table("use_case_uploads")
    with op.batch_alter_table("use_case_runs") as batch:
        batch.drop_constraint("fk_use_case_run_execution", type_="foreignkey")
        batch.drop_column("execution_run_id")
    op.drop_column("conversations", "purpose")
