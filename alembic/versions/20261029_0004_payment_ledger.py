"""Add Safepay payment and append-only ledger tables.

Revision ID: 20261029_0004
Revises: 20261029_0003
"""
from alembic import op
import sqlalchemy as sa

revision = "20261029_0004"
down_revision = "20261029_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "payments" not in tables:
        op.create_table(
            "payments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("public_id", sa.String(36), nullable=False, unique=True),
            sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointments.id"), nullable=False),
            sa.Column("client_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("amount_minor", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="PKR"),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("provider", sa.String(32), nullable=False, server_default="safepay"),
            sa.Column("provider_tracker", sa.String(120), nullable=True),
            sa.Column("provider_transaction", sa.String(120), nullable=True),
            sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
            sa.Column("checkout_url", sa.Text(), nullable=True),
            sa.Column("refund_amount_minor", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_provider_event_id", sa.String(180), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("provider_tracker", name="uq_payments_provider_tracker"),
        )
        op.create_index("ix_payments_public_id", "payments", ["public_id"], unique=True)
        op.create_index("ix_payments_appointment_id", "payments", ["appointment_id"])
        op.create_index("ix_payments_client_id", "payments", ["client_id"])
        op.create_index("ix_payments_appointment_status", "payments", ["appointment_id", "status"])
    if "payment_ledger_entries" not in tables:
        op.create_table(
            "payment_ledger_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=False),
            sa.Column("event_key", sa.String(180), nullable=False, unique=True),
            sa.Column("event_type", sa.String(40), nullable=False),
            sa.Column("amount_minor", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="PKR"),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("provider_reference", sa.String(120), nullable=True),
            sa.Column("note", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_payment_ledger_entries_payment_id", "payment_ledger_entries", ["payment_id"])
        op.create_index("ix_payment_ledger_payment_created", "payment_ledger_entries", ["payment_id", "created_at"])


def downgrade() -> None:
    # Preserve financial/audit data. Roll back application code without dropping ledger history.
    pass
