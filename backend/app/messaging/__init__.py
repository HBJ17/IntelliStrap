"""Messenger factory. List logic talks to WhatsApp only through get_messenger()."""
import threading

from ..config import get_settings
from .base import Messenger, MessagingError, ParsedReply, format_items_inline  # noqa: F401

_instance: Messenger | None = None
_lock = threading.Lock()


def _build(mode: str) -> Messenger:
    if mode == "simulator":
        from .simulator import SimulatorMessenger
        return SimulatorMessenger()
    if mode == "twilio_sandbox":
        from .twilio_sandbox import TwilioSandboxMessenger
        return TwilioSandboxMessenger(get_settings())
    if mode == "twilio_production":
        from .twilio_production import TwilioProductionMessenger
        return TwilioProductionMessenger(get_settings())
    raise ValueError(f"unknown MESSAGING_MODE {mode!r}")


def get_messenger() -> Messenger:
    global _instance
    with _lock:
        if _instance is None:
            _instance = _build(get_settings().messaging_mode)
        return _instance


def set_messenger(messenger: Messenger | None) -> None:
    global _instance
    with _lock:
        _instance = messenger
