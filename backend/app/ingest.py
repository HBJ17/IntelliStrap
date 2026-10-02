"""ingest_event(): the single entry point for strap events (HTTP, MQTT and the simulator)."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock, settings_store
from .models import Event, EventType, Strap, StrapState
from .schemas import PAYLOAD_MODELS


class PayloadError(ValueError):
    pass


@dataclass
class IngestResult:
    stored: bool
    event: Event | None = None


def validate_payload(event_type: EventType, payload: dict) -> dict:
    try:
        model = PAYLOAD_MODELS[event_type].model_validate(payload)
    except Exception as exc:  # pydantic.ValidationError
        raise PayloadError(str(exc)) from exc
    return model.model_dump(exclude_none=True)


def _drift_throttled(db: Session, strap: Strap, now: datetime) -> bool:
    window = timedelta(minutes=settings_store.get_int(db, "drift_throttle_minutes"))
    last = db.scalar(
        select(Event.ts)
        .where(Event.device_id == strap.device_id, Event.type == EventType.baseline_drift)
        .order_by(Event.ts.desc())
        .limit(1)
    )
    return last is not None and now - last < window


def ingest_event(db: Session, strap: Strap, event_type: EventType | str, payload: dict,
                 now: datetime | None = None) -> IngestResult:
    """R1: validate, log with a server timestamp, update the strap row, then apply list rules."""
    now = now or clock.now()
    event_type = EventType(event_type)
    data = validate_payload(event_type, payload)

    strap.last_seen = now
    strap.offline_alerted_at = None
    if "baseline" in data:
        strap.baseline = data["baseline"]
    if "gap" in data:
        strap.gap = data["gap"]
    if "rssi" in data:
        strap.rssi = data["rssi"]

    if event_type == EventType.baseline_drift and _drift_throttled(db, strap, now):
        db.flush()
        return IngestResult(stored=False)

    event = Event(device_id=strap.device_id, ts=now, type=event_type, value=data)
    db.add(event)

    if event_type == EventType.state_change:
        new_state = StrapState(data["state"])
        if new_state != strap.state:
            strap.state = new_state
            strap.state_since = now
    db.flush()
    return IngestResult(stored=True, event=event)


def pop_commands(strap: Strap) -> list[str]:
    if not strap.pending_command:
        return []
    commands = [strap.pending_command]
    strap.pending_command = None
    return commands
