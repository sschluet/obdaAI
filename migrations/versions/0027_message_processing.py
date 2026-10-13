"""Link answers to their actual runs without guessing historical provenance."""

import json
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("answer_model_used", sa.Boolean(), nullable=True))
    # SQLite cannot add a foreign key after table creation without batch mode.
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("run_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_messages_run_id", "runs", ["run_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_messages_run_id", ["run_id"])
    backfill_exact_answers()


def backfill_exact_answers() -> None:
    """Only one exact event output and one answer in the same conversation.

    Count inactive branches too: a repeated answer cannot be attributed from
    ordering or timestamps. Malformed/incomplete event records stay unknown.
    Never modify message content or infer model usage from privacy labels.
    """
    bind = op.get_bind()
    conversations = (
        bind.execute(
            sa.text("SELECT DISTINCT conversation_id FROM messages WHERE role = 'assistant'")
        )
        .scalars()
        .all()
    )
    for conversation_id in conversations:
        messages: dict[str, list[str]] = defaultdict(list)
        for identifier, content in bind.execute(
            sa.text(
                "SELECT id, content FROM messages "
                "WHERE conversation_id = :conversation AND role = 'assistant'"
            ),
            {"conversation": conversation_id},
        ):
            messages[content].append(identifier)
        chunks: dict[str, list[str]] = defaultdict(list)
        invalid: set[str] = set()
        for run_id, payload in bind.execute(
            sa.text(
                "SELECT events.run_id, events.payload FROM run_events AS events "
                "JOIN runs ON runs.id = events.run_id "
                "WHERE runs.conversation_id = :conversation AND events.kind = 'delta' "
                "ORDER BY events.run_id, events.sequence"
            ),
            {"conversation": conversation_id},
        ):
            try:
                value = json.loads(payload)
                text = value.get("text") if isinstance(value, dict) else None
                if not isinstance(text, str):
                    invalid.add(run_id)
                else:
                    chunks[run_id].append(text)
            except (ValueError, TypeError):
                invalid.add(run_id)
        candidates: dict[str, list[str]] = defaultdict(list)
        for run_id, output in chunks.items():
            combined = "".join(output)
            if combined and run_id not in invalid:
                candidates[combined].append(run_id)
        for content, identifiers in messages.items():
            runs = candidates.get(content, [])
            if len(identifiers) == len(runs) == 1:
                bind.execute(
                    sa.text(
                        "UPDATE messages SET run_id = :run WHERE id = :message AND run_id IS NULL"
                    ),
                    {"run": runs[0], "message": identifiers[0]},
                )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM messages WHERE run_id IS NOT NULL")) or (
        op.get_bind().scalar(
            sa.text("SELECT count(*) FROM runs WHERE answer_model_used IS NOT NULL")
        )
    ):
        raise RuntimeError("Preserve message processing provenance before downgrade")
    with op.batch_alter_table("messages") as batch:
        batch.drop_index("ix_messages_run_id")
        batch.drop_constraint("fk_messages_run_id", type_="foreignkey")
        batch.drop_column("run_id")
    op.drop_column("runs", "answer_model_used")
