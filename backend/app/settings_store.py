"""Global key/value settings (app_settings table) with defaults."""
from sqlalchemy.orm import Session

from .models import AppSetting

DEFAULTS: dict[str, int] = {
    "hold_seconds": 20,
    "reminder_hours": 6,
    "expiry_days": 3,
    "offline_minutes": 15,
    "event_retention_days": 30,
    "drift_throttle_minutes": 15,
    "refill_reminder_days": 4,
}


def get_int(db: Session, key: str) -> int:
    row = db.get(AppSetting, key)
    return int(row.value) if row is not None else DEFAULTS[key]


def get_all(db: Session) -> dict[str, int]:
    stored = {row.key: int(row.value) for row in db.query(AppSetting).all() if row.key in DEFAULTS}
    return {**DEFAULTS, **stored}


def set_values(db: Session, values: dict[str, int]) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            raise KeyError(key)
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=str(int(value))))
        else:
            row.value = str(int(value))
    db.flush()
