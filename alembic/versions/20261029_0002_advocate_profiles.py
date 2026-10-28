"""Backfill directory profiles for advocate accounts created by old app versions.

Revision ID: 20261029_0002
Revises: 20261029_0001
Create Date: 2026-10-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261029_0002"
down_revision = "20261029_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if not {"users", "lawyers"}.issubset(tables):
        return

    users = sa.Table("users", sa.MetaData(), autoload_with=bind)
    lawyers = sa.Table("lawyers", sa.MetaData(), autoload_with=bind)

    # Minimal columns must exist for a safe backfill. Optional legacy columns
    # are mapped to NULL when unavailable on a very old schema.
    if not {"id", "name", "role"}.issubset(users.c.keys()):
        return
    if not {"user_id", "name"}.issubset(lawyers.c.keys()):
        return

    def user_value(column_name: str):
        return users.c[column_name] if column_name in users.c else sa.null()

    values = {
        "user_id": users.c.id,
        "name": users.c.name,
        "specialty": sa.literal("General Practice"),
        # Never copy users.address into a publicly visible lawyer address.
        "address": sa.null(),
        "chamber_address": user_value("chamber_address"),
        "city": user_value("city"),
        "area": user_value("area"),
        "phone": user_value("phone"),
        "is_verified": sa.false(),
        "license_number": user_value("license_number"),
        "bar_association": user_value("bar_association"),
        "experience_years": user_value("experience_years"),
    }
    target_names = [name for name in values if name in lawyers.c]
    target_values = [values[name] for name in target_names]

    role_filter = users.c.role == "advocate"
    statement = sa.insert(lawyers).from_select(
        target_names,
        sa.select(*target_values)
        .select_from(users)
        .where(role_filter)
        .where(
            ~sa.exists(
                sa.select(sa.literal(1))
                .select_from(lawyers)
                .where(lawyers.c.user_id == users.c.id)
            )
        ),
    )
    bind.execute(statement)


def downgrade() -> None:
    # Backfilled rows may have been edited or verified after migration. Do not
    # delete them automatically during downgrade.
    pass
