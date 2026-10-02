"""Shows WhatsApp messages on the dashboard instead of sending them (no Twilio account needed)."""
import itertools
import threading
from typing import Mapping

from .. import clock
from .base import (KEYWORD_FOOTER, MessagingError, ParsedReply, button_payload, owner_list_text, parse_reply_form,
                   shop_order_text)

MAX_MESSAGES = 200


class SimulatorMessenger:
    mode = "simulator"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self.messages: list[dict] = []
        # Roles listed here fail on send, to exercise error handling ("owner_list", "shop_order", "text").
        self.fail_roles: set[str] = set()

    def _record(self, role: str, to: str, text: str, order_id: int | None = None,
                buttons: list[dict] | None = None) -> str:
        if role in self.fail_roles:
            raise MessagingError(f"simulated {role} delivery failure", transient=False)
        with self._lock:
            sid = f"SIM{next(self._ids):05d}"
            self.messages.append({"sid": sid, "ts": clock.now().isoformat(), "role": role, "to": to, "text": text,
                                  "order_id": order_id, "buttons": buttons or []})
            del self.messages[:-MAX_MESSAGES]
        return sid

    def send_owner_list(self, order) -> list[str]:
        buttons = [{"title": "Order", "payload": button_payload(order.id, "order")},
                   {"title": "Not now", "payload": button_payload(order.id, "not_now")}]
        text = f"{owner_list_text(order)}\n{KEYWORD_FOOTER}"
        return [self._record("owner_list", order.owner.whatsapp_number, text, order.id, buttons)]

    def send_shop_order(self, order) -> list[str]:
        return [self._record("shop_order", order.shop.whatsapp_number, shop_order_text(order), order.id)]

    def send_text(self, to: str, text: str) -> str:
        return self._record("text", to, text)

    def parse_webhook(self, form: Mapping[str, str]) -> ParsedReply | None:
        return parse_reply_form(form)

    def clear(self) -> None:
        with self._lock:
            self.messages.clear()
