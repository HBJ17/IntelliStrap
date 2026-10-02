import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, Enum as SAEnum, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime


class StrapState(str, enum.Enum):
    OK = "OK"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class EventType(str, enum.Enum):
    state_change = "state_change"
    recalibration = "recalibration"
    baseline_drift = "baseline_drift"
    heartbeat = "heartbeat"


class ListStatus(str, enum.Enum):
    pending = "pending"
    ordered = "ordered"
    fulfilled = "fulfilled"
    cancelled = "cancelled"


class OrderStatus(str, enum.Enum):
    awaiting_owner = "awaiting_owner"
    confirmed = "confirmed"
    sent_to_shop = "sent_to_shop"
    cancelled = "cancelled"
    expired = "expired"
    send_failed = "send_failed"


OPEN_LIST_STATUSES = (ListStatus.pending, ListStatus.ordered)


def _enum(cls: type[enum.Enum], name: str) -> SAEnum:
    # Non-native enum = plain VARCHAR, portable between SQLite and Postgres.
    return SAEnum(cls, name=name, native_enum=False, length=20,
                  values_callable=lambda e: [m.value for m in e])


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    whatsapp_number: Mapped[str] = mapped_column(String(20))
    opted_in: Mapped[bool] = mapped_column(Boolean, default=False)


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    whatsapp_number: Mapped[str] = mapped_column(String(20))
    list_threshold_inr: Mapped[int] = mapped_column(Integer, default=400)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"), nullable=True)

    shop: Mapped[Shop | None] = relationship()


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(20), default="")
    pack_size: Mapped[str] = mapped_column(String(40), default="")
    price_inr: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Strap(Base):
    __tablename__ = "straps"

    device_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("owners.id"), nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    claim_code: Mapped[str | None] = mapped_column(String(6), nullable=True, unique=True)
    device_token_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[StrapState] = mapped_column(_enum(StrapState, "strap_state"), default=StrapState.UNKNOWN)
    state_since: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    gap: Mapped[float | None] = mapped_column(Float, nullable=True)
    rssi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    pending_command: Mapped[str | None] = mapped_column(String(32), nullable=True)
    offline_alerted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    owner: Mapped[Owner | None] = relationship()
    item: Mapped[Item | None] = relationship()


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_device_ts", "device_id", "ts"),
        Index("ix_events_type_ts", "type", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("straps.device_id"))
    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    type: Mapped[EventType] = mapped_column(_enum(EventType, "event_type"))
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id"))
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"), nullable=True)
    total_inr: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus, "order_status"), default=OrderStatus.awaiting_owner)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    owner_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sent_to_shop_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    twilio_message_ids: Mapped[list] = mapped_column(JSON, default=list)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner: Mapped[Owner] = relationship()
    shop: Mapped[Shop | None] = relationship()
    rows: Mapped[list["ListItem"]] = relationship(back_populates="order", order_by="ListItem.id")


class ListItem(Base):
    __tablename__ = "list_items"
    __table_args__ = (
        # At most one open row per strap. NULL strap_id (manual rows) is not constrained.
        Index(
            "uq_list_items_open_strap", "strap_id", unique=True,
            sqlite_where=text("status IN ('pending', 'ordered')"),
            postgresql_where=text("status IN ('pending', 'ordered')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id"))
    strap_id: Mapped[str | None] = mapped_column(ForeignKey("straps.device_id"), nullable=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    price_at_time_inr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[ListStatus] = mapped_column(_enum(ListStatus, "list_status"), default=ListStatus.pending)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    refill_reminder_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    strap: Mapped[Strap | None] = relationship()
    item: Mapped[Item] = relationship()
    order: Mapped[Order | None] = relationship(back_populates="rows")

    @property
    def needs_price(self) -> bool:
        return self.price_at_time_inr is None

    @property
    def line_total_inr(self) -> int | None:
        return None if self.price_at_time_inr is None else self.price_at_time_inr * self.qty


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
