"""Billing: plan/pack columns on users, quota_pool on jobs; subscriptions,
payments, refunds and webhook_events (PR #12).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from alembic import op

from holt_server.migrations._util import add_column, create_index, create_table

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

LIVE = sa.text("status IN ('created', 'authenticated', 'active', 'pending') "
               "AND NOT cancel_at_period_end")


def upgrade() -> None:
    # Existing rows get defaults, so NOT NULL columns can be added in place.
    add_column("users", sa.Column("plan_until", sa.DateTime(timezone=True), nullable=True))
    add_column("users", sa.Column("cycle_start", sa.DateTime(timezone=True), nullable=True))
    add_column("users", sa.Column("pack_credits", sa.Integer(), nullable=False,
                                  server_default="0"))
    add_column("users", sa.Column("packs_frozen", sa.Boolean(), nullable=False,
                                  server_default=sa.false()))
    add_column("users", sa.Column("plan_subscription_id", sa.String(length=100),
                                  nullable=True))
    # Billing-cycle period keys ("c2026-09-25T10:00") outgrow "YYYY-MM".
    with op.batch_alter_table("users") as batch:
        batch.alter_column("ai_period", existing_type=sa.String(length=7),
                           type_=sa.String(length=20), existing_nullable=False)
    add_column("jobs", sa.Column("quota_pool", sa.String(length=8), nullable=True))

    create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=100), nullable=False),
        sa.Column("plan", sa.String(length=40), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_subscription_id"),
    )
    create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    create_index("ux_subscriptions_one_live", "subscriptions", ["user_id"], unique=True,
                 postgresql_where=LIVE, sqlite_where=LIVE)

    create_table(
        "payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("item", sa.String(length=40), nullable=False),
        sa.Column("provider_order_id", sa.String(length=100), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=100), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=100), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("credited", sa.Boolean(), nullable=False),
        sa.Column("refunded_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credits_left", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credits_taken", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disputed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reports", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_order_id"),
        sa.UniqueConstraint("provider_payment_id"),
    )
    # Columns added to payments during review: no-ops on a table made just
    # above, but a preview's create_all copy of the table may predate them.
    add_column("payments", sa.Column("refunded_amount", sa.Integer(), nullable=False,
                                     server_default="0"))
    add_column("payments", sa.Column("credits_left", sa.Integer(), nullable=False,
                                     server_default="0"))
    add_column("payments", sa.Column("credits_taken", sa.Integer(), nullable=False,
                                     server_default="0"))
    add_column("payments", sa.Column("disputed", sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    add_column("payments", sa.Column("reports", sa.Integer(), nullable=False,
                                     server_default="0"))
    create_index("ix_payments_user_id", "payments", ["user_id"])
    create_index("ix_payments_provider_subscription_id", "payments",
                 ["provider_subscription_id"])

    create_table(
        "refunds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_refund_id", sa.String(length=100), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_refund_id"),
    )
    create_index("ix_refunds_payment_id", "refunds", ["payment_id"])

    create_table(
        "webhook_events",
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider", "event_id"),
    )


def downgrade() -> None:
    for table in ("webhook_events", "refunds", "payments", "subscriptions"):
        op.drop_table(table)
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("quota_pool")
    with op.batch_alter_table("users") as batch:
        for column in ("plan_subscription_id", "packs_frozen", "pack_credits",
                       "cycle_start", "plan_until"):
            batch.drop_column(column)
