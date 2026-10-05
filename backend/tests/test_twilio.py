"""Phase 4: Twilio messengers, signed webhook, keyword fallback, reminders and expiry (R11)."""
import json
from types import SimpleNamespace

import pytest
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator

from app import clock, scheduler
from app.config import get_settings
from app.messaging import MessagingError, set_messenger
from app.messaging.base import parse_keyword, parse_reply_form
from app.messaging.twilio_production import TwilioProductionMessenger
from app.messaging.twilio_sandbox import TwilioSandboxMessenger
from app.models import ListItem, ListStatus, Order, OrderStatus

WEBHOOK_URL = "https://smartband.example.test/webhooks/twilio"
OWNER = "whatsapp:+919000000001"


class FakeTwilioClient:
    def __init__(self, fail_with: Exception | None = None):
        self.sent: list[dict] = []
        self.fail_with = fail_with
        self.messages = self

    def create(self, **kwargs):
        if self.fail_with:
            raise self.fail_with
        self.sent.append(kwargs)
        return SimpleNamespace(sid=f"SM{len(self.sent):04d}")


def settings_with(**overrides):
    return get_settings().model_copy(update=overrides)


def signed_post(client, form: dict, token: str = "test-twilio-token"):
    signature = RequestValidator(token).compute_signature(WEBHOOK_URL, form)
    return client.post("/webhooks/twilio", data=form, headers={"X-Twilio-Signature": signature})


@pytest.fixture
def twilio(demo):
    fake = FakeTwilioClient()
    set_messenger(TwilioSandboxMessenger(settings_with(), client=fake))
    return fake


def make_order(demo, auth_client, session) -> Order:
    for name in ["Rice", "Toor dal", "Poha", "Sago"]:
        auth_client.post("/api/list/items", json={"item_id": demo["items"][name]})
    return session.query(Order).one()


def to_shop(fake):
    return [m for m in fake.sent if m["to"] == "whatsapp:+919000000002"]


# --- webhook signature --------------------------------------------------------------------

def test_webhook_rejects_missing_or_bad_signature(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    form = {"From": OWNER, "ButtonPayload": f"order:{order.id}:yes", "ButtonText": "Order"}
    assert client.post("/webhooks/twilio", data=form).status_code == 403
    assert signed_post(client, form, token="wrong-token").status_code == 403
    tampered = {**form, "ButtonPayload": f"order:{order.id}:no"}
    sig = RequestValidator("test-twilio-token").compute_signature(WEBHOOK_URL, form)
    assert client.post("/webhooks/twilio", data=tampered, headers={"X-Twilio-Signature": sig}).status_code == 403
    session.expire_all()
    assert order.status == OrderStatus.awaiting_owner and to_shop(twilio) == []


def test_webhook_accepts_valid_signature(client, demo, twilio):
    r = signed_post(client, {"From": OWNER, "Body": "hello"})
    assert r.status_code == 200 and "<Response>" in r.text


# --- Phase 4 check: Order delivers to the shop exactly once -----------------------------------

def test_order_button_sends_shop_list_exactly_once(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    owner_msg = twilio.sent[0]
    assert owner_msg["to"] == OWNER and owner_msg["from_"] == "whatsapp:+14155238886"
    assert owner_msg["body"].startswith("Your pantry list is ₹410: Rice ×1 ₹60, Toor dal ×1 ₹150")
    assert "Reply ORDER to send to the shop or NO to skip." in owner_msg["body"]

    form = {"From": OWNER, "ButtonPayload": f"order:{order.id}:yes", "ButtonText": "Order"}
    assert signed_post(client, form).status_code == 200
    assert signed_post(client, form).status_code == 200  # double tap
    shop = to_shop(twilio)
    assert len(shop) == 1
    assert shop[0]["body"] == ("New order from Asha: Rice ×1 ₹60, Toor dal ×1 ₹150, Poha ×1 ₹90, Sago ×1 ₹110. "
                               "Total ₹410. Please confirm delivery. Reply CONFIRM to accept or CANT to decline.")
    owner_texts = [m["body"] for m in twilio.sent if m["to"] == OWNER][1:]
    assert owner_texts[0] == "Sent to Corner Shop." and "already handled" in owner_texts[1]
    session.expire_all()
    assert order.status == OrderStatus.sent_to_shop


def test_keyword_order_reply(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    signed_post(client, {"From": OWNER, "Body": " order! "})
    assert len(to_shop(twilio)) == 1
    session.expire_all()
    assert order.status == OrderStatus.sent_to_shop


def test_keyword_no_cancels_and_returns_rows(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    signed_post(client, {"From": OWNER, "Body": "No"})
    session.expire_all()
    assert order.status == OrderStatus.cancelled
    assert session.query(ListItem).filter_by(status=ListStatus.pending).count() == 4
    assert to_shop(twilio) == []


def test_reply_from_stranger_is_ignored(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    signed_post(client, {"From": "whatsapp:+15550001111", "ButtonPayload": f"order:{order.id}:yes"})
    session.expire_all()
    assert order.status == OrderStatus.awaiting_owner and to_shop(twilio) == []


def test_parse_reply_variants():
    assert parse_reply_form({"From": OWNER, "ButtonPayload": "order:42:yes"}).order_id == 42
    assert parse_reply_form({"From": OWNER, "ButtonPayload": "order:42:no"}).action == "not_now"
    assert parse_reply_form({"From": OWNER, "ButtonText": "Not now"}).action == "not_now"
    assert parse_reply_form({"From": OWNER, "Body": "YES"}).from_number == "+919000000001"
    assert parse_reply_form({"From": OWNER, "Body": "what is this?"}) is None
    assert parse_keyword("not now.") == "not_now" and parse_keyword("ok") is None


def test_parse_reply_swapped_template_button():
    # Seen live: the template's button text held the pair and its id was a plain name.
    form = {"From": OWNER, "Body": "Place order:18:yes", "ButtonText": "Place order:18:yes", "ButtonPayload": "PLACE_ORDER"}
    reply = parse_reply_form(form)
    assert reply.action == "order" and reply.order_id == 18 and reply.from_number == "+919000000001"
    assert parse_reply_form({"From": OWNER, "ButtonText": "Not now:18:no"}).action == "not_now"
    assert parse_reply_form({"From": OWNER, "Body": "call 5551234 now"}) is None


# --- messenger implementations -----------------------------------------------------------

def test_sandbox_uses_template_when_configured(demo, auth_client, session):
    fake = FakeTwilioClient()
    set_messenger(TwilioSandboxMessenger(settings_with(twilio_content_sid_owner="HXowner"), client=fake))
    order = make_order(demo, auth_client, session)
    sent = fake.sent[0]
    assert sent["content_sid"] == "HXowner" and "body" not in sent
    assert json.loads(sent["content_variables"]) == {
        "1": "Rice ×1 ₹60, Toor dal ×1 ₹150, Poha ×1 ₹90, Sago ×1 ₹110", "2": "410", "3": str(order.id)}


def test_production_requires_templates(demo, auth_client, session):
    fake = FakeTwilioClient()
    set_messenger(TwilioProductionMessenger(settings_with(twilio_content_sid_owner=""), client=fake))
    order = make_order(demo, auth_client, session)
    session.expire_all()
    assert order.status == OrderStatus.send_failed and "TWILIO_CONTENT_SID_OWNER" in order.last_error
    assert fake.sent == []


def test_production_sends_both_templates(client, demo, auth_client, session):
    fake = FakeTwilioClient()
    set_messenger(TwilioProductionMessenger(
        settings_with(twilio_content_sid_owner="HXowner", twilio_content_sid_shop="HXshop"), client=fake))
    order = make_order(demo, auth_client, session)
    signed_post(client, {"From": OWNER, "ButtonPayload": f"order:{order.id}:yes"})
    shop = to_shop(fake)
    assert shop[0]["content_sid"] == "HXshop"
    assert json.loads(shop[0]["content_variables"]) == {
        "1": "Asha", "2": "Rice ×1 ₹60, Toor dal ×1 ₹150, Poha ×1 ₹90, Sago ×1 ₹110", "3": "410",
        "4": str(order.id)}  # {{4}} feeds the "Confirm delivery" button id shop:{{4}}:confirm


SHOP = "whatsapp:+919000000002"


def send_to_shop_via_owner(client, order):
    assert signed_post(client, {"From": OWNER, "ButtonPayload": f"order:{order.id}:yes"}).status_code == 200


def texts_to(fake, number):
    return [m["body"] for m in fake.sent if m["to"] == number and "body" in m]


def test_shop_confirms_delivery_once(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    send_to_shop_via_owner(client, order)
    form = {"From": SHOP, "ButtonPayload": f"shop:{order.id}:confirm", "ButtonText": "Confirm delivery"}
    assert signed_post(client, form).status_code == 200
    assert signed_post(client, form).status_code == 200  # double tap
    session.expire_all()
    assert order.status == OrderStatus.delivery_confirmed
    assert any("is confirmed" in t for t in texts_to(twilio, SHOP))
    assert sum("will deliver it" in t for t in texts_to(twilio, OWNER)) == 1  # owner told exactly once
    assert any("already handled" in t for t in texts_to(twilio, SHOP))


def test_shop_confirms_with_typed_keyword(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    send_to_shop_via_owner(client, order)
    assert signed_post(client, {"From": SHOP, "Body": "Delivered"}).status_code == 200
    session.expire_all()
    assert order.status == OrderStatus.delivery_confirmed


def test_confirm_button_title_alone_works(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    send_to_shop_via_owner(client, order)
    assert signed_post(client, {"From": SHOP, "ButtonText": "Confirm delivery", "ButtonPayload": "X"}).status_code == 200
    session.expire_all()
    assert order.status == OrderStatus.delivery_confirmed


def test_only_the_orders_shop_can_confirm(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    send_to_shop_via_owner(client, order)
    stranger = {"From": "whatsapp:+15550009999", "ButtonPayload": f"shop:{order.id}:confirm"}
    assert signed_post(client, stranger).status_code == 200
    session.expire_all()
    assert order.status == OrderStatus.sent_to_shop  # unchanged


def test_shop_cannot_confirm_before_the_owner_orders(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)  # list sent to the owner, who has not replied yet
    assert signed_post(client, {"From": SHOP, "ButtonPayload": f"shop:{order.id}:confirm"}).status_code == 200
    session.expire_all()
    assert order.status == OrderStatus.awaiting_owner


def test_shop_reply_parsing():
    assert parse_reply_form({"From": SHOP, "ButtonPayload": "shop:7:confirm"}).order_id == 7
    assert parse_reply_form({"From": SHOP, "ButtonPayload": "shop:7:confirm"}).action == "shop_confirm"
    assert parse_reply_form({"From": SHOP, "Body": "Confirm delivery"}).action == "shop_confirm"
    assert parse_reply_form({"From": SHOP, "ButtonPayload": "shop:7:decline"}).action == "shop_decline"
    assert parse_reply_form({"From": SHOP, "ButtonPayload": "shop:7:decline"}).order_id == 7
    assert parse_reply_form({"From": SHOP, "ButtonText": "Can't deliver"}).action == "shop_decline"
    assert parse_reply_form({"From": SHOP, "Body": "out of stock"}).action == "shop_decline"
    assert parse_reply_form({"From": SHOP, "Body": "DELIVERED."}).action == "shop_confirm"
    assert parse_keyword("done") == "shop_confirm" and parse_keyword("hello") is None


@pytest.mark.parametrize("status,transient", [(500, True), (503, True), (429, True), (400, False)])
def test_twilio_errors_map_to_messaging_error(demo, status, transient):
    exc = TwilioRestException(status, "https://api.twilio.com", msg="boom", code=63016)
    sleeps: list[float] = []
    messenger = TwilioSandboxMessenger(settings_with(), client=FakeTwilioClient(fail_with=exc), sleep=sleeps.append)
    with pytest.raises(MessagingError) as info:
        messenger.send_text("+919000000001", "hi")
    assert info.value.transient is transient
    assert sleeps == ([1.0, 2.0] if transient else [])  # 3 tries with backoff, then give up


def test_missing_credentials_is_a_messaging_error(demo):
    messenger = TwilioSandboxMessenger(settings_with(twilio_account_sid="", twilio_auth_token=""))
    with pytest.raises(MessagingError):
        messenger.send_text("+919000000001", "hi")


# --- R11 ------------------------------------------------------------------------------------

def test_r11_one_reminder_then_expiry(demo, auth_client, session, sim):
    order = make_order(demo, auth_client, session)
    clock.advance(hours=5, minutes=59)
    scheduler.run_frequent()
    assert len([m for m in sim.messages if m["role"] == "owner_list"]) == 1

    clock.advance(minutes=2)
    scheduler.run_frequent()
    clock.advance(hours=12)
    scheduler.run_frequent()
    assert len([m for m in sim.messages if m["role"] == "owner_list"]) == 2  # exactly one reminder
    session.expire_all()
    assert order.reminder_sent_at is not None and order.status == OrderStatus.awaiting_owner

    clock.advance(days=3)
    scheduler.run_frequent()
    session.expire_all()
    assert order.status == OrderStatus.expired
    assert session.query(ListItem).filter_by(status=ListStatus.pending).count() == 4
    assert any("expired" in m["text"] for m in sim.messages if m["role"] == "text")
    # Tapping Order on an expired list does nothing.
    r = auth_client.post("/api/sim/reply", json={"order_id": order.id, "action": "order"})
    assert r.json()["outcome"] == "already_handled"


def test_shop_declines_and_items_return_to_list(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    send_to_shop_via_owner(client, order)
    form = {"From": SHOP, "ButtonPayload": f"shop:{order.id}:decline", "ButtonText": "Can't deliver"}
    assert signed_post(client, form).status_code == 200
    assert signed_post(client, form).status_code == 200  # double tap
    session.expire_all()
    assert order.status == OrderStatus.shop_declined
    assert sum("can't deliver order" in t for t in texts_to(twilio, OWNER)) == 1
    assert session.query(ListItem).filter(ListItem.status == ListStatus.pending).count() == 4  # back on the list
    assert any("already handled" in t for t in texts_to(twilio, SHOP))


def test_shop_typed_no_also_declines(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    send_to_shop_via_owner(client, order)
    assert signed_post(client, {"From": SHOP, "Body": "NO"}).status_code == 200
    session.expire_all()
    assert order.status == OrderStatus.shop_declined


def test_confirmed_order_cannot_be_declined_later(client, demo, twilio, auth_client, session):
    order = make_order(demo, auth_client, session)
    send_to_shop_via_owner(client, order)
    signed_post(client, {"From": SHOP, "ButtonPayload": f"shop:{order.id}:confirm"})
    signed_post(client, {"From": SHOP, "ButtonPayload": f"shop:{order.id}:decline"})
    session.expire_all()
    assert order.status == OrderStatus.delivery_confirmed
