"""Business rules (spec Section 6). Messaging goes through app.messaging only."""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import settings_store
from .models import Owner, Strap


def get_owner(db: Session) -> Owner:
    """Single-owner prototype: the first owner row, created on demand."""
    owner = db.query(Owner).order_by(Owner.id).first()
    if owner is None:
        owner = Owner(name="Home", whatsapp_number="", list_threshold_inr=400)
        db.add(owner)
        db.flush()
    return owner


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
