"""Optional personal background with explicit field sharing."""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "personal_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("fields", sa.Text(), nullable=False),
        sa.Column("cloud_fields", sa.Text(), nullable=False),
        sa.CheckConstraint("id = 1 AND revision >= 0", name="personal_profile_singleton"),
    )
    op.bulk_insert(table, [{"id": 1, "revision": 0, "enabled": False,
                            "fields": "{}", "cloud_fields": "[]"}])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT count(*) FROM personal_profile WHERE revision > 0 OR enabled "
        "OR fields <> '{}' OR cloud_fields <> '[]'"
    )):
        raise RuntimeError("Preserve personal information before downgrade")
    op.drop_table("personal_profile")
