import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Literal, Mapping, Protocol

if TYPE_CHECKING:
    from ..models import ListItem, Order

Action = Literal["order", "not_now", "shop_confirm", "shop_decline"]


@dataclass
class ParsedReply:
    action: Action
    order_id: int | None = None      # None = keyword reply; tie to the sender's latest open order
    from_number: str | None = None   # E.164, without the "whatsapp:" prefix


class MessagingError(Exception):
    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class Messenger(Protocol):
    mode: str

    def send_owner_list(self, order: "Order") -> list[str]: ...
    def send_shop_order(self, order: "Order") -> list[str]: ...
    def send_text(self, to: str, text: str) -> str: ...
    def parse_webhook(self, form: Mapping[str, str]) -> ParsedReply | None: ...


# --- message text (shared by every implementation) --------------------------

KEYWORD_FOOTER = "Reply ORDER to send to the shop or NO to skip."
SHOP_KEYWORD_FOOTER = "Reply CONFIRM to accept or CANT to decline."


def format_items_inline(rows: Iterable["ListItem"]) -> str:
    """`Rice ×1 ₹60, Toor dal ×1 ₹150` — templates cannot contain line breaks."""
    return ", ".join(f"{row.item.name} ×{row.qty} ₹{row.line_total_inr}" for row in rows)


def owner_list_text(order: "Order") -> str:
    return f"Your pantry list is ₹{order.total_inr}: {format_items_inline(order.rows)}. Send this order to your shop?"


def shop_order_text(order: "Order") -> str:
    return (f"New order from {order.owner.name}: {format_items_inline(order.rows)}. "
            f"Total ₹{order.total_inr}. Please confirm delivery.")


def owner_template_variables(order: "Order") -> dict[str, str]:
    return {"1": format_items_inline(order.rows), "2": str(order.total_inr), "3": str(order.id)}


def shop_template_variables(order: "Order") -> dict[str, str]:
    # {{4}} is the order id, used in the "Confirm delivery" button id (shop:{{4}}:confirm).
    return {"1": order.owner.name, "2": format_items_inline(order.rows), "3": str(order.total_inr),
            "4": str(order.id)}


def button_payload(order_id: int, action: Action) -> str:
    if action == "shop_confirm":
        return f"shop:{order_id}:confirm"
    if action == "shop_decline":
        return f"shop:{order_id}:decline"
    return f"order:{order_id}:{'yes' if action == 'order' else 'no'}"


# --- inbound replies -----------------------------------------------------------

_PAYLOAD_RE = re.compile(r"^order:(\d+):(yes|no)$")
_EMBEDDED_RE = re.compile(r"(?:^|[^\d])(\d+):(yes|no)\b", re.IGNORECASE)
_SHOP_PAYLOAD_RE = re.compile(r"shop:(\d+):(confirm|decline)", re.IGNORECASE)
_ORDER_WORDS = {"ORDER", "YES", "Y", "CONFIRM"}
_NO_WORDS = {"NO", "N", "NOT NOW", "NOTNOW", "SKIP", "CANCEL"}
# The shop's button titles are "Confirm" and "Can't deliver"; these also work typed.
_SHOP_CONFIRM_WORDS = {"CONFIRMED", "CONFIRM DELIVERY", "DELIVERED", "DONE", "ACCEPT", "ACCEPTED"}
_SHOP_DECLINE_WORDS = {"CANT DELIVER", "CANNOT DELIVER", "CANT", "CANNOT", "DECLINE", "DECLINED", "REJECT",
                       "UNAVAILABLE", "OUT OF STOCK"}


def strip_whatsapp(address: str | None) -> str | None:
    if not address:
        return None
    return address.removeprefix("whatsapp:").strip() or None


def parse_keyword(body: str | None) -> Action | None:
    words = re.sub(r"[^A-Z ]", "", (body or "").upper()).split()
    text = " ".join(words)
    if text in _ORDER_WORDS:
        return "order"
    if text in _NO_WORDS:
        return "not_now"
    if text in _SHOP_CONFIRM_WORDS:
        return "shop_confirm"
    if text in _SHOP_DECLINE_WORDS:
        return "shop_decline"
    return None


def parse_reply_form(form: Mapping[str, str]) -> ParsedReply | None:
    """Button payload (`order:42:yes`) first, then the ORDER / NO keyword fallback."""
    sender = strip_whatsapp(form.get("From"))
    payload = (form.get("ButtonPayload") or "").strip()
    match = _PAYLOAD_RE.match(payload)
    if match:
        return ParsedReply("order" if match.group(2) == "yes" else "not_now", int(match.group(1)), sender)
    for field in (payload, form.get("ButtonText"), form.get("Body")):
        shop_match = _SHOP_PAYLOAD_RE.search(field or "")
        if shop_match:
            action = "shop_confirm" if shop_match.group(2).lower() == "confirm" else "shop_decline"
            return ParsedReply(action, int(shop_match.group(1)), sender)
    # A template whose button text and id were swapped sends the `<n>:yes|no` pair as the button text
    # (e.g. "Place order:18:yes"). Take the order id and answer from there.
    for field in (form.get("ButtonText"), form.get("Body")):
        embedded = _EMBEDDED_RE.search(field or "")
        if embedded:
            return ParsedReply("order" if embedded.group(2).lower() == "yes" else "not_now",
                               int(embedded.group(1)), sender)
    action = parse_keyword(form.get("ButtonText")) or parse_keyword(form.get("Body"))
    if action:
        return ParsedReply(action, None, sender)
    return None
