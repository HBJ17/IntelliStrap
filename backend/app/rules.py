"""Business rules (spec Section 6). Messaging goes through app.messaging only."""
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.orm import Session

from . import settings_store
from .config import get_settings
from .messaging import Messenger, MessagingError, ParsedReply, get_messenger
from .models import (OPEN_LIST_STATUSES, Event, Item, ListItem, ListStatus, Order, OrderStatus, Owner, Shop, Strap,
                     StrapState)

log = logging.getLogger(__name__)


class RuleError(ValueError):
    """A request that the rules refuse (shown to the dashboard user)."""


def get_owner(db: Session) -> Owner:
    """Single-owner prototype: the first owner row, created on demand."""
    owner = db.query(Owner).order_by(Owner.id).first()
    if owner is None:
        owner = Owner(name="Home", whatsapp_number="", list_threshold_inr=400)
        db.add(owner)
        db.flush()
    return owner


# --- strap status (R10) ----------------------------------------------------------

def is_offline(strap: Strap, now: datetime, offline_minutes: int) -> bool:
    """R10: no report within offline_minutes. Computed; never overwrites the stored state."""
    return strap.last_seen is None or now - strap.last_seen > timedelta(minutes=offline_minutes)


def strap_status(strap: Strap, now: datetime, offline_minutes: int) -> str:
    if strap.last_seen is None:
        return "UNKNOWN"
    if is_offline(strap, now, offline_minutes):
        return "OFFLINE"
    return strap.state.value


def offline_minutes(db: Session) -> int:
    return settings_store.get_int(db, "offline_minutes")


def hold_delta(db: Session) -> timedelta:
    dev_seconds = get_settings().dev_hold_seconds
    if dev_seconds is not None:
        return timedelta(seconds=dev_seconds)
    return timedelta(seconds=settings_store.get_int(db, "hold_seconds"))


# --- contents labels ---------------------------------------------------------------

def find_or_create_item(db: Session, label: str) -> Item:
    """Match a typed label to the catalog (case-insensitive); unknown labels become new, unpriced items."""
    name = " ".join(label.split())
    item = db.scalars(select(Item).where(func.lower(Item.name) == name.lower())).first()
    if item is None:
        item = Item(name=name, unit="", pack_size="", price_inr=None)
        db.add(item)
        db.flush()
    return item


def delete_strap(db: Session, strap: Strap) -> None:
    """Pending row is cancelled; past list rows and orders are kept, just unlinked from the strap."""
    for row in db.scalars(select(ListItem).where(ListItem.strap_id == strap.device_id)):
        if row.status == ListStatus.pending:
            row.status = ListStatus.cancelled
        row.strap_id = None
    db.flush()
    db.execute(delete(Event).where(Event.device_id == strap.device_id))
    db.delete(strap)
    db.flush()


# --- list rows -------------------------------------------------------------------

def open_row_for_strap(db: Session, strap_id: str) -> ListItem | None:
    return db.scalars(select(ListItem).where(ListItem.strap_id == strap_id,
                                             ListItem.status.in_(OPEN_LIST_STATUSES))).first()


def pending_rows(db: Session, owner: Owner) -> list[ListItem]:
    return list(db.scalars(select(ListItem).where(ListItem.owner_id == owner.id,
                                                  ListItem.status == ListStatus.pending)
                           .order_by(ListItem.added_at, ListItem.id)))


def priced_total(rows: list[ListItem]) -> int:
    """R9: unpriced rows are excluded, never counted as ₹0."""
    return sum(row.line_total_inr for row in rows if not row.needs_price)


def add_list_item(db: Session, owner: Owner, item: Item, now: datetime, strap: Strap | None = None) -> ListItem:
    """R3/R4: one open row per strap; price copied from the catalog (None = needs price)."""
    if strap is not None and open_row_for_strap(db, strap.device_id) is not None:
        raise RuleError("this strap is already on the list")
    row = ListItem(owner_id=owner.id, strap_id=strap.device_id if strap else None, item_id=item.id, qty=1,
                   price_at_time_inr=item.price_inr, status=ListStatus.pending, added_at=now)
    db.add(row)
    db.flush()
    return row


def on_state_change(db: Session, strap: Strap, new_state: StrapState, now: datetime) -> None:
    """R5: a refill clears the strap's row (pending -> cancelled, ordered -> fulfilled)."""
    if new_state != StrapState.OK:
        return
    row = open_row_for_strap(db, strap.device_id)
    if row is None:
        return
    row.status = ListStatus.cancelled if row.status == ListStatus.pending else ListStatus.fulfilled
    db.flush()


def evaluate_holds(db: Session, now: datetime, messenger: Messenger | None = None,
                   hold: timedelta | None = None) -> list[ListItem]:
    """R2/R3/R6/R10: straps LOW for the whole hold time, online and labelled, join the list."""
    hold = hold_delta(db) if hold is None else hold
    off_minutes = offline_minutes(db)
    has_open_row = exists().where(ListItem.strap_id == Strap.device_id, ListItem.status.in_(OPEN_LIST_STATUSES))
    candidates = db.scalars(
        select(Strap).where(Strap.state == StrapState.LOW, Strap.owner_id.is_not(None), Strap.item_id.is_not(None),
                            Strap.state_since <= now - hold, ~has_open_row)
        .order_by(Strap.state_since)
    ).all()
    added = []
    for strap in candidates:
        if is_offline(strap, now, off_minutes):
            continue
        added.append(add_list_item(db, strap.owner, strap.item, now, strap=strap))
        check_threshold(db, strap.owner, now, messenger)
    return added


def reprice_pending(db: Session, item: Item, now: datetime, messenger: Messenger | None = None) -> None:
    """A price entered later fills unpriced pending rows for that item, then re-checks the threshold."""
    if item.price_inr is None:
        return
    rows = db.scalars(select(ListItem).where(ListItem.item_id == item.id, ListItem.status == ListStatus.pending,
                                             ListItem.price_at_time_inr.is_(None))).all()
    for row in rows:
        row.price_at_time_inr = item.price_inr
    db.flush()
    for owner_id in {row.owner_id for row in rows}:
        check_threshold(db, db.get(Owner, owner_id), now, messenger)


def list_summary(db: Session, owner: Owner) -> dict:
    rows = pending_rows(db, owner)
    missing = {row.item_id: row.item.name for row in rows if row.needs_price}
    return {
        "rows": rows,
        "total_inr": priced_total(rows),
        "threshold_inr": owner.list_threshold_inr,
        "missing_prices": [{"item_id": k, "name": v} for k, v in missing.items()],
    }


# --- orders ------------------------------------------------------------------------

def check_threshold(db: Session, owner: Owner, now: datetime, messenger: Messenger | None = None) -> Order | None:
    """R6: once the priced pending total reaches the threshold, order the priced rows."""
    rows = [row for row in pending_rows(db, owner) if not row.needs_price]
    if rows and priced_total(rows) >= owner.list_threshold_inr:
        return create_order(db, owner, rows, now, messenger)
    return None


def send_now(db: Session, owner: Owner, now: datetime, messenger: Messenger | None = None) -> Order:
    """R8: send below the threshold; needs at least one row and every price present (R9)."""
    rows = pending_rows(db, owner)
    if not rows:
        raise RuleError("the shopping list is empty")
    missing = sorted({row.item.name for row in rows if row.needs_price})
    if missing:
        raise RuleError("enter a price first for: " + ", ".join(missing))
    return create_order(db, owner, rows, now, messenger)


def create_order(db: Session, owner: Owner, rows: list[ListItem], now: datetime,
                 messenger: Messenger | None = None) -> Order:
    """R7: rows are locked to the order; later LOW jars start the next list."""
    order = Order(owner_id=owner.id, shop_id=owner.shop_id, total_inr=priced_total(rows),
                  status=OrderStatus.awaiting_owner, created_at=now, twilio_message_ids=[])
    db.add(order)
    db.flush()
    for row in rows:
        row.status = ListStatus.ordered
        row.order = order
    db.flush()
    deliver_owner_list(db, order, now, messenger)
    return order


def record_sids(order: Order, role: str, sids: list[str]) -> None:
    order.twilio_message_ids = [*(order.twilio_message_ids or []), *({"role": role, "sid": s} for s in sids)]


def _fail(order: Order, reason: str) -> None:
    order.status = OrderStatus.send_failed
    order.last_error = reason
    log.warning("order %s send failed: %s", order.id, reason)


def safe_text(messenger: Messenger, to: str | None, text: str) -> str | None:
    if not to:
        return None
    try:
        return messenger.send_text(to, text)
    except MessagingError as exc:
        log.warning("text to owner failed: %s", exc)
        return None


def deliver_owner_list(db: Session, order: Order, now: datetime, messenger: Messenger | None = None) -> bool:
    messenger = messenger or get_messenger()
    if not order.owner.whatsapp_number:
        _fail(order, "owner WhatsApp number is not set")
        db.flush()
        return False
    try:
        sids = messenger.send_owner_list(order)
    except MessagingError as exc:
        _fail(order, f"could not send the list to the owner: {exc}")
        db.flush()
        return False
    order.status = OrderStatus.awaiting_owner
    order.owner_sent_at = now
    order.last_error = None
    record_sids(order, "owner", sids)
    db.flush()
    return True


def send_to_shop(db: Session, order: Order, now: datetime, messenger: Messenger | None = None) -> bool:
    messenger = messenger or get_messenger()
    shop = order.owner.shop
    order.shop = shop
    if shop is None or not shop.whatsapp_number:
        reason = "no shop WhatsApp number is set"
    elif not shop.opted_in:
        reason = f"{shop.name} has not opted in to WhatsApp messages"
    else:
        try:
            sids = messenger.send_shop_order(order)
        except MessagingError as exc:
            reason = str(exc)
        else:
            order.status = OrderStatus.sent_to_shop
            order.sent_to_shop_at = now
            order.last_error = None
            record_sids(order, "shop", sids)
            db.flush()
            safe_text(messenger, order.owner.whatsapp_number, f"Sent to {shop.name}.")
            return True
    _fail(order, reason)
    db.flush()
    safe_text(messenger, order.owner.whatsapp_number,
              f"Could not send order #{order.id} to the shop: {reason}. It is saved; retry from the dashboard.")
    return False


def return_rows_to_pending(order: Order) -> None:
    for row in list(order.rows):
        if row.status == ListStatus.ordered:
            row.status = ListStatus.pending
            row.order = None


def claim_order(db: Session, order: Order, new_status: OrderStatus, allowed: tuple[OrderStatus, ...]) -> bool:
    """Atomic status transition: only one caller can move an order out of `allowed`."""
    result = db.execute(update(Order).where(Order.id == order.id, Order.status.in_(allowed))
                        .values(status=new_status).execution_options(synchronize_session=False))
    db.refresh(order)
    return result.rowcount == 1


def handle_reply(db: Session, reply: ParsedReply, now: datetime, messenger: Messenger | None = None) -> str:
    """Owner tapped Order / Not now (or replied ORDER / NO). R14: acts once, then 'already handled'."""
    messenger = messenger or get_messenger()
    if reply.action in ("shop_confirm", "shop_decline") or _is_shop_only_sender(db, reply.from_number):
        return handle_shop_reply(db, reply, messenger)
    owner = None
    if reply.from_number:
        owner = db.scalars(select(Owner).where(Owner.whatsapp_number == reply.from_number)).first()
        if owner is None:
            return "unknown_sender"

    if reply.order_id is not None:
        order = db.get(Order, reply.order_id)
        if order is None or (owner is not None and order.owner_id != owner.id):
            return "unknown_order"
    else:
        owner = owner or get_owner(db)
        order = db.scalars(select(Order).where(Order.owner_id == owner.id,
                                               Order.status == OrderStatus.awaiting_owner)
                           .order_by(Order.created_at.desc(), Order.id.desc())).first()
        if order is None:
            safe_text(messenger, owner.whatsapp_number, "There is no pantry list waiting for your reply.")
            return "no_open_order"

    target = OrderStatus.confirmed if reply.action == "order" else OrderStatus.cancelled
    if not claim_order(db, order, target, (OrderStatus.awaiting_owner,)):
        safe_text(messenger, order.owner.whatsapp_number,
                  f"Order #{order.id} was already handled ({order.status.value.replace('_', ' ')}).")
        return "already_handled"

    if reply.action == "order":
        return "sent_to_shop" if send_to_shop(db, order, now, messenger) else "send_failed"
    return_rows_to_pending(order)
    db.flush()
    safe_text(messenger, order.owner.whatsapp_number, "OK, not ordering now. The items stay on your list.")
    return "cancelled"


def _is_shop_only_sender(db: Session, number: str | None) -> bool:
    """A reply from a number that is a shop's and not the owner's (the same phone can play both roles in a demo)."""
    if not number:
        return False
    is_shop = db.scalars(select(Shop.id).where(Shop.whatsapp_number == number)).first() is not None
    is_owner = db.scalars(select(Owner.id).where(Owner.whatsapp_number == number)).first() is not None
    return is_shop and not is_owner


def handle_shop_reply(db: Session, reply: ParsedReply, messenger: Messenger) -> str:
    """The shopkeeper accepted or declined an order (button or typed). Acts once; only the order's own shop may."""
    declining = reply.action in ("shop_decline", "not_now")  # a plain NO from the shop also means "can't deliver"
    shop = None
    if reply.from_number:
        shop = db.scalars(select(Shop).where(Shop.whatsapp_number == reply.from_number)).first()
    if shop is None:
        return "unknown_sender"

    if reply.order_id is not None:
        order = db.get(Order, reply.order_id)
        if order is None or order.shop_id != shop.id:
            return "unknown_order"
    else:
        order = db.scalars(select(Order).where(Order.shop_id == shop.id, Order.status == OrderStatus.sent_to_shop)
                           .order_by(Order.created_at.desc(), Order.id.desc())).first()
        if order is None:
            safe_text(messenger, shop.whatsapp_number, "There is no order waiting for your answer.")
            return "no_open_order"

    target = OrderStatus.shop_declined if declining else OrderStatus.delivery_confirmed
    if not claim_order(db, order, target, (OrderStatus.sent_to_shop,)):
        safe_text(messenger, shop.whatsapp_number,
                  f"Order #{order.id} was already handled ({order.status.value.replace('_', ' ')}).")
        return "already_handled"
    if declining:
        return_rows_to_pending(order)  # back on the list; the owner decides what to do next
        db.flush()
        safe_text(messenger, shop.whatsapp_number, f"OK, order #{order.id} is marked as not deliverable.")
        safe_text(messenger, order.owner.whatsapp_number,
                  f"{shop.name} can't deliver order #{order.id}. The items are back on your list.")
        return "shop_declined"
    db.flush()
    safe_text(messenger, shop.whatsapp_number, f"Thanks! Order #{order.id} is confirmed.")
    safe_text(messenger, order.owner.whatsapp_number, f"{shop.name} confirmed order #{order.id} and will deliver it.")
    return "delivery_confirmed"


def retry_order(db: Session, order: Order, now: datetime, messenger: Messenger | None = None) -> bool:
    """Dashboard retry of an unsent order: resend to the owner, or to the shop if the owner already said Order."""
    if order.status != OrderStatus.send_failed:
        raise RuleError("only unsent orders can be retried")
    if order.owner_sent_at is None:
        return deliver_owner_list(db, order, now, messenger)
    if not claim_order(db, order, OrderStatus.confirmed, (OrderStatus.send_failed,)):
        raise RuleError("order was already handled")
    return send_to_shop(db, order, now, messenger)


def cancel_order(db: Session, order: Order) -> None:
    if not claim_order(db, order, OrderStatus.cancelled, (OrderStatus.awaiting_owner, OrderStatus.send_failed)):
        raise RuleError("only open or unsent orders can be cancelled")
    return_rows_to_pending(order)
    db.flush()
