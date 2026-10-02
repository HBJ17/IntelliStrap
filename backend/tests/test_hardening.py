"""Section 9 security/reliability matrix (hardware-only rows are covered in the README runbook)."""
import json
from types import SimpleNamespace

import pytest
from twilio.base.exceptions import TwilioRestException

from app import clock, mqtt_adapter, scheduler
from app.config import Settings, get_settings
from app.main import create_app
from app.messaging import set_messenger
from app.messaging.twilio_sandbox import TwilioSandboxMessenger
from app.models import Event, ListItem, ListStatus, Order, OrderStatus, Strap


def make_order(demo, auth_client, session) -> Order:
    for name in ["Rice", "Toor dal", "Poha", "Sago"]:
        auth_client.post("/api/list/items", json={"item_id": demo["items"][name]})
    return session.query(Order).one()


# --- rate limits and payload sizes ------------------------------------------------------------

def test_login_rate_limited(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_MINUTE", "3")
    get_settings.cache_clear()
    codes = [client.post("/api/login", json={"password": "nope"}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_device_endpoints_rate_limited(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DEVICE_PER_MINUTE", "2")
    get_settings.cache_clear()
    codes = [client.get("/api/device/commands").status_code for _ in range(3)]
    assert codes == [401, 401, 429]


def test_oversized_body_rejected(client, demo):
    big = {"type": "heartbeat", "payload": {"x": "a" * 20_000}}
    r = client.post("/api/device/events", headers=demo["straps"]["Rice"]["headers"], json=big)
    assert r.status_code == 413


def test_security_headers(client):
    r = client.get("/api/me")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"


# --- secrets ------------------------------------------------------------------------------------

def test_placeholder_secrets_refused_outside_dev(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "change-me")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        with TestClient(create_app(init_database=False)):
            pass


def test_session_cookie_secure_outside_dev(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    r = client.post("/api/login", json={"password": "test-password"})
    cookie = r.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_insecure_defaults_listed():
    s = Settings(dashboard_password="change-me", session_secret="x" * 32, device_provision_secret="")
    assert s.insecure_defaults() == ["DASHBOARD_PASSWORD", "DEVICE_PROVISION_SECRET"]


# --- Meta/Twilio outage: retry, then show as unsent ----------------------------------------------

class FlakyClient:
    def __init__(self, failures: int):
        self.failures = failures
        self.sent = []
        self.messages = self

    def create(self, **kwargs):
        if self.failures:
            self.failures -= 1
            raise TwilioRestException(503, "https://api.twilio.com", msg="unavailable")
        self.sent.append(kwargs)
        return SimpleNamespace(sid=f"SM{len(self.sent)}")


def test_transient_outage_recovers_within_retries(demo, auth_client, session):
    fake = FlakyClient(failures=2)
    set_messenger(TwilioSandboxMessenger(get_settings(), client=fake, sleep=lambda s: None))
    order = make_order(demo, auth_client, session)
    session.expire_all()
    assert order.status == OrderStatus.awaiting_owner and len(fake.sent) == 1


def test_long_outage_marks_order_unsent_and_retry_works(demo, auth_client, session):
    fake = FlakyClient(failures=10)
    set_messenger(TwilioSandboxMessenger(get_settings(), client=fake, sleep=lambda s: None))
    order = make_order(demo, auth_client, session)
    orders = auth_client.get("/api/orders").json()
    assert orders[0]["unsent"] is True and "503" in orders[0]["last_error"]
    fake.failures = 0
    assert auth_client.post(f"/api/orders/{order.id}/retry").json()["status"] == "awaiting_owner"


# --- R12: ordered but never refilled -----------------------------------------------------------

def test_r12_ordered_not_refilled_one_reminder_no_duplicate(demo, strap_event, auth_client, session, sim):
    for name in ["Rice", "Toor dal", "Poha", "Sago"]:
        strap_event(demo["straps"][name], "state_change", {"state": "LOW"})
    clock.advance(minutes=21)
    for s in demo["straps"].values():
        strap_event(s, "heartbeat", {})
    scheduler.run_frequent()
    order = session.query(Order).one()
    auth_client.post("/api/sim/reply", json={"order_id": order.id, "action": "order"})
    strap_event(demo["straps"]["Rice"], "state_change", {"state": "OK"})  # rice refilled, the rest not

    for _ in range(5):  # five days, jars still LOW and reporting
        clock.advance(days=1)
        for name in ["Rice", "Toor dal", "Poha", "Sago"]:
            strap_event(demo["straps"][name], "heartbeat", {})
        scheduler.run_frequent()

    reminders = [m["text"] for m in sim.messages if m["role"] == "text" and "still reads LOW" in m["text"]]
    assert len(reminders) == 3 and not any(r.startswith("Rice") for r in reminders)
    session.expire_all()
    assert session.query(Order).count() == 1
    assert session.query(ListItem).filter_by(status=ListStatus.pending).count() == 0


# --- strap silent -> Offline + one alert -----------------------------------------------------

def test_offline_alert_sent_once_and_rearmed(demo, strap_event, session, sim):
    rice = demo["straps"]["Rice"]
    clock.advance(minutes=16)
    for name in ["Toor dal", "Poha", "Sago"]:
        strap_event(demo["straps"][name], "heartbeat", {})
    scheduler.run_frequent()
    scheduler.run_frequent()
    alerts = [m for m in sim.messages if "has not reported" in m["text"]]
    assert len(alerts) == 1 and alerts[0]["text"].startswith("Rice jar")

    strap_event(rice, "heartbeat", {})  # back online re-arms the alert
    assert session.get(Strap, rice["device_id"]).offline_alerted_at is None


# --- MQTT adapter ------------------------------------------------------------------------------

class FakeMqtt:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, json.loads(payload)))


def test_mqtt_events_use_same_ingest(demo, session):
    device_id = demo["straps"]["Rice"]["device_id"]
    strap = session.get(Strap, device_id)
    strap.pending_command = "recalibrate"
    session.commit()
    fake = FakeMqtt()
    msg = json.dumps({"type": "state_change", "payload": {"state": "LOW", "gap": 9.0}}).encode()
    assert mqtt_adapter.handle_message(fake, f"smartband/{device_id}/events", msg)
    assert fake.published == [(f"smartband/{device_id}/commands", {"commands": ["recalibrate"]})]
    session.expire_all()
    assert session.query(Event).count() == 1 and session.get(Strap, device_id).state.value == "LOW"


def test_mqtt_rejects_unknown_device_and_bad_payload(demo, session):
    fake = FakeMqtt()
    good = json.dumps({"type": "heartbeat", "payload": {}}).encode()
    assert not mqtt_adapter.handle_message(fake, "smartband/sb-UNKNOWN00000/events", good)
    assert not mqtt_adapter.handle_message(fake, "smartband/../events", good)
    rice = demo["straps"]["Rice"]["device_id"]
    assert not mqtt_adapter.handle_message(fake, f"smartband/{rice}/events", b"not json")
    assert not mqtt_adapter.handle_message(fake, f"smartband/{rice}/events", b"x" * 5000)
    assert session.query(Event).count() == 0


# --- no internet during demo: simulator still runs the whole flow -----------------------------

def test_simulator_runs_full_flow_offline(demo, auth_client, session, sim):
    order = make_order(demo, auth_client, session)
    auth_client.post("/api/sim/reply", json={"order_id": order.id, "action": "order"})
    assert [m["role"] for m in sim.messages] == ["owner_list", "shop_order", "text"]
