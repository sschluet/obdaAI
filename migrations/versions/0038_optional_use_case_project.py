"""Allow standalone Use Cases without losing existing project links or results."""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def change_nullable(nullable: bool) -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    deferred = False
    if sqlite:
        # SQLite recreates this parent table. Keep child references enabled and
        # defer their transient missing-parent check until the replacement exists.
        deferred = bool(connection.scalar(sa.text("PRAGMA defer_foreign_keys")))
        connection.execute(sa.text("PRAGMA defer_foreign_keys=ON"))
    with op.batch_alter_table("use_cases") as batch:
        batch.alter_column("project_id", existing_type=sa.String(36), nullable=nullable)
    if sqlite:
        if connection.execute(sa.text("PRAGMA foreign_key_check")).first() is not None:
            raise RuntimeError("Use Case migration left invalid foreign key references")
        # SQLite retains a deferred DROP counter even after a same-named parent
        # is recreated. Clear it only after verifying every actual reference.
        connection.execute(sa.text("PRAGMA defer_foreign_keys=OFF"))
        if deferred:
            connection.execute(sa.text("PRAGMA defer_foreign_keys=ON"))


def upgrade() -> None:
    change_nullable(True)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM use_cases WHERE project_id IS NULL")):
        raise RuntimeError("Associate standalone Use Cases with projects before downgrade")
    change_nullable(False)
