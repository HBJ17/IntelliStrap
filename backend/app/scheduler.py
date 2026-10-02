"""Periodic jobs. State lives in the DB, so nothing is lost when the process restarts (R2)."""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import clock, rules, settings_store
from .config import get_settings
from .db import session_scope
from .messaging import Messenger, MessagingError, get_messenger
from .models import Event, EventType, Order, OrderStatus

log = logging.getLogger(__name__)

PRUNABLE_TYPES = (EventType.baseline_drift, EventType.heartbeat)


def prune_events(db: Session, now: datetime) -> int:
    """R13: drop old drift/heartbeat events. state_change, recalibration and orders are kept."""
    cutoff = now - timedelta(days=settings_store.get_int(db, "event_retention_days"))
    result = db.execute(delete(Event).where(Event.type.in_(PRUNABLE_TYPES), Event.ts < cutoff))
    return result.rowcount or 0


def order_reminders_and_expiry(db: Session, now: datetime, messenger: Messenger | None = None) -> None:
    """R11: one reminder after reminder_hours, expiry after expiry_days (rows go back to pending)."""
    messenger = messenger or get_messenger()
    remind_after = timedelta(hours=settings_store.get_int(db, "reminder_hours"))
    expire_after = timedelta(days=settings_store.get_int(db, "expiry_days"))
    waiting = db.scalars(select(Order).where(Order.status == OrderStatus.awaiting_owner)).all()
    for order in waiting:
        sent_at = order.owner_sent_at or order.created_at
        if now - sent_at >= expire_after:
            if rules.claim_order(db, order, OrderStatus.expired, (OrderStatus.awaiting_owner,)):
                rules.return_rows_to_pending(order)
                db.flush()
                rules.safe_text(messenger, order.owner.whatsapp_number,
                                f"Your pantry list (order #{order.id}) expired without a reply. "
                                "The items stay on your list.")
        elif order.reminder_sent_at is None and now - sent_at >= remind_after:
            # The reminder re-sends the list itself (an approved template in production).
            try:
                sids = messenger.send_owner_list(order)
            except MessagingError as exc:
                log.warning("reminder for order %s failed: %s", order.id, exc)
                continue
            order.reminder_sent_at = now
            rules.record_sids(order, "reminder", sids)
            db.flush()


def run_frequent(now: datetime | None = None, messenger: Messenger | None = None) -> None:
    now = now or clock.now()
    with session_scope() as db:
        rules.evaluate_holds(db, now, messenger)
        order_reminders_and_expiry(db, now, messenger)


def run_daily(now: datetime | None = None) -> None:
    now = now or clock.now()
    with session_scope() as db:
        removed = prune_events(db, now)
    log.info("pruned %d old heartbeat/drift events", removed)


def _safe(job):
    def wrapper():
        try:
            job()
        except Exception:
            log.exception("scheduled job %s failed", job.__name__)
    wrapper.__name__ = job.__name__
    return wrapper


def start() -> BackgroundScheduler:
    # With DEV_HOLD_SECONDS set (demos), check every few seconds instead of every minute.
    dev_seconds = get_settings().dev_hold_seconds
    interval = 60 if dev_seconds is None else max(2, min(60, dev_seconds // 2 or 2))
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(_safe(run_frequent), "interval", seconds=interval, id="frequent", max_instances=1,
                      coalesce=True)
    scheduler.add_job(_safe(run_daily), "interval", hours=24, id="daily", max_instances=1, coalesce=True,
                      next_run_time=clock.now() + timedelta(minutes=1))
    scheduler.start()
    log.info("scheduler started (frequent job every %ss)", interval)
    return scheduler
