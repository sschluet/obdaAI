"""Preserve reconstructable pre-revision chat context before allowing edits."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for run in bind.execute(
        sa.text("SELECT id, conversation_id, started FROM runs WHERE context_snapshot = ''")
    ).mappings():
        messages = list(
            bind.execute(
                sa.text(
                    "SELECT id, role, content, label, revision FROM messages "
                    "WHERE conversation_id = :chat "
                    "AND created <= :started ORDER BY created, id"
                ),
                {"chat": run["conversation_id"], "started": run["started"]},
            ).mappings()
        )
        snapshot = {
            "parts": [
                {
                    "content": m["content"],
                    "label": m["label"],
                    "source_id": m["id"],
                    "revision": m["revision"],
                }
                for m in messages
            ],
            "roles": [m["role"] for m in messages],
            "backfilled": True,
        }
        bind.execute(
            sa.text("UPDATE runs SET context_snapshot=:snapshot WHERE id=:id"),
            {"snapshot": json.dumps(snapshot, ensure_ascii=False), "id": run["id"]},
        )


def downgrade() -> None:
    # Historical content is evidence; never erase it during a downgrade.
    pass
