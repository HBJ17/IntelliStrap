"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

OPEN = sa.text("status IN ('pending', 'ordered')")


def upgrade() -> None:
    op.create_table(
        "shops",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("whatsapp_number", sa.String(20), nullable=False),
        sa.Column("opted_in", sa.Boolean, nullable=False),
    )
    op.create_table(
        "owners",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("whatsapp_number", sa.String(20), nullable=False),
        sa.Column("list_threshold_inr", sa.Integer, nullable=False),
        sa.Column("shop_id", sa.Integer, sa.ForeignKey("shops.id"), nullable=True),
    )
    op.create_table(
        "items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("pack_size", sa.String(40), nullable=False),
        sa.Column("price_inr", sa.Integer, nullable=True),
    )
    op.create_table(
        "straps",
        sa.Column("device_id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("owners.id"), nullable=True),
        sa.Column("display_name", sa.Text, nullable=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=True),
        sa.Column("claim_code", sa.String(6), nullable=True, unique=True),
        sa.Column("device_token_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("state_since", sa.DateTime, nullable=True),
        sa.Column("baseline", sa.Float, nullable=True),
        sa.Column("gap", sa.Float, nullable=True),
        sa.Column("rssi", sa.Integer, nullable=True),
        sa.Column("last_seen", sa.DateTime, nullable=True),
        sa.Column("pending_command", sa.String(32), nullable=True),
        sa.Column("offline_alerted_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("device_id", sa.String(32), sa.ForeignKey("straps.device_id"), nullable=False),
        sa.Column("ts", sa.DateTime, nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("value", sa.JSON, nullable=False),
    )
    op.create_index("ix_events_device_ts", "events", ["device_id", "ts"])
    op.create_index("ix_events_type_ts", "events", ["type", "ts"])
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("owners.id"), nullable=False),
        sa.Column("shop_id", sa.Integer, sa.ForeignKey("shops.id"), nullable=True),
        sa.Column("total_inr", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("owner_sent_at", sa.DateTime, nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime, nullable=True),
        sa.Column("sent_to_shop_at", sa.DateTime, nullable=True),
        sa.Column("twilio_message_ids", sa.JSON, nullable=False),
        sa.Column("last_error", sa.Text, nullable=True),
    )
    op.create_table(
        "list_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("owners.id"), nullable=False),
        sa.Column("strap_id", sa.String(32), sa.ForeignKey("straps.device_id"), nullable=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("price_at_time_inr", sa.Integer, nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("added_at", sa.DateTime, nullable=False),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("refill_reminder_sent_at", sa.DateTime, nullable=True),
    )
    op.create_index("uq_list_items_open_strap", "list_items", ["strap_id"], unique=True,
                    sqlite_where=OPEN, postgresql_where=OPEN)
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_index("uq_list_items_open_strap", table_name="list_items")
    op.drop_table("list_items")
    op.drop_table("orders")
    op.drop_index("ix_events_type_ts", table_name="events")
    op.drop_index("ix_events_device_ts", table_name="events")
    op.drop_table("events")
    op.drop_table("straps")
    op.drop_table("items")
    op.drop_table("owners")
    op.drop_table("shops")
