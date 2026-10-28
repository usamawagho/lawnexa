"""Add server-backed appointment type/mode/fee fields.

Revision ID: 20261029_0003
Revises: 20261029_0002
Create Date: 2026-10-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261029_0003"
down_revision = "20261029_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "appointments" not in tables:
        return
    existing = {column["name"] for column in sa.inspect(bind).get_columns("appointments")}
    additions = (
        ("meeting_type", sa.String(length=20)),
        ("meeting_mode", sa.String(length=20)),
        ("consultation_fee", sa.Integer()),
    )
    for column_name, column_type in additions:
        if column_name not in existing:
            op.add_column("appointments", sa.Column(column_name, column_type, nullable=True))
            existing.add(column_name)
    if "meeting_type" in existing:
        op.execute(sa.text("UPDATE appointments SET meeting_type = 'physical' WHERE meeting_type IS NULL OR meeting_type = ''"))
    if "meeting_mode" in existing:
        op.execute(sa.text("UPDATE appointments SET meeting_mode = 'chamber' WHERE meeting_mode IS NULL OR meeting_mode = ''"))


def downgrade() -> None:
    # Keep historical appointment information and any post-migration values.
    pass
