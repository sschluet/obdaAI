"""Install pinned upstream queue schema in its own namespace (PostgreSQL only)."""

from alembic import op
from procrastinate.schema import SchemaManager

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.exec_driver_sql("CREATE SCHEMA hub_queue")
    bind.exec_driver_sql("SET LOCAL search_path TO hub_queue, public")
    # No parameters: preserve upstream percent signs and multi-statement SQL.
    bind.connection.driver_connection.execute(SchemaManager.get_schema())
    bind.exec_driver_sql("SET LOCAL search_path TO public")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP SCHEMA hub_queue CASCADE")
