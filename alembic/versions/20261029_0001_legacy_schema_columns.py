"""Repair known missing columns in older LawNexa SQLite/PostgreSQL databases.

Revision ID: 20261029_0001
Revises:
Create Date: 2026-10-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261029_0001"
down_revision = None
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns(table_name)
    }


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)

    # The migration also runs against a brand-new database before create_all.
    # Missing tables are therefore skipped; create_all creates their full schema.
    additive_columns = {
        "users": (("residential_address", sa.String(length=255)),),
        "lawyers": (("chamber_address", sa.String(length=255)),),
        "appointments": (("created_at", sa.DateTime()),),
    }

    for table_name, columns in additive_columns.items():
        if table_name not in tables:
            continue
        existing = _column_names(bind, table_name)
        for column_name, column_type in columns:
            if column_name not in existing:
                op.add_column(
                    table_name,
                    sa.Column(column_name, column_type, nullable=True),
                )
                existing.add(column_name)

    # Backfill existing appointment rows that predate created_at. Keep the
    # column nullable to avoid rejecting imported/historical records.
    if "appointments" in tables and "created_at" in _column_names(bind, "appointments"):
        op.execute(
            sa.text(
                "UPDATE appointments "
                "SET created_at = CURRENT_TIMESTAMP "
                "WHERE created_at IS NULL"
            )
        )


def downgrade() -> None:
    # Intentional no-op: dropping these columns would destroy values captured
    # after this migration. Rollback should be performed from a database backup.
    pass
