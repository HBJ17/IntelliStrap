"""Single source of "now" so tests can control time without sleeping."""
from datetime import datetime, timedelta, timezone

_override: datetime | None = None


def now() -> datetime:
    return _override if _override is not None else datetime.now(timezone.utc)


def set_now(value: datetime) -> None:
    global _override
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    _override = value


def advance(**kwargs) -> datetime:
    set_now(now() + timedelta(**kwargs))
    return now()


def reset() -> None:
    global _override
    _override = None
