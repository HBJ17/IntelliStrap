import os

# Must be set before app modules read settings.
os.environ.update(
    APP_ENV="dev",
    DATABASE_URL="sqlite://",
    DASHBOARD_PASSWORD="test-password",
    SESSION_SECRET="test-session-secret",
    DEVICE_PROVISION_SECRET="test-provision",
    PUBLIC_BASE_URL="https://smartband.example.test",
    MESSAGING_MODE="simulator",
    TWILIO_AUTH_TOKEN="test-twilio-token",
    DEV_HOLD_SECONDS="",
    SCHEDULER_ENABLED="false",
    MQTT_ENABLED="false",
)

from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import clock, db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.messaging import get_messenger, set_messenger  # noqa: E402
from app.models import Base  # noqa: E402

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fresh_state():
    get_settings.cache_clear()
    set_messenger(None)
    engine = db.configure("sqlite://")
    Base.metadata.create_all(engine)
    clock.set_now(T0)
    yield
    clock.reset()
    Base.metadata.drop_all(engine)


@pytest.fixture
def session():
    s = db.SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client():
    with TestClient(create_app(init_database=False)) as c:
        yield c


@pytest.fixture
def register(client):
    def _register(device_id: str = "sb-TEST00000001") -> dict:
        r = client.post("/api/device/register",
                        json={"device_id": device_id, "provision_secret": "test-provision"})
        assert r.status_code == 200, r.text
        data = r.json()
        data["headers"] = {"Authorization": f"Bearer {data['device_token']}", "X-Device-Id": device_id}
        return data
    return _register


@pytest.fixture
def sim():
    return get_messenger()


@pytest.fixture
def strap_event(client):
    def _send(strap: dict, event_type: str, payload: dict | None = None):
        r = client.post("/api/device/events", headers=strap["headers"],
                        json={"type": event_type, "payload": payload or {}})
        assert r.status_code == 200, r.text
        return r.json()
    return _send


@pytest.fixture
def auth_client(client):
    r = client.post("/api/login", json={"password": "test-password"})
    assert r.status_code == 200
    return client


@pytest.fixture
def demo(session):
    """Owner/shop/catalog with four claimed straps that last reported at T0."""
    from app.models import Item, Owner, Shop, Strap, StrapState
    from app.security import hash_token

    shop = Shop(name="Corner Shop", whatsapp_number="+919000000002", opted_in=True)
    owner = Owner(name="Asha", whatsapp_number="+919000000001", list_threshold_inr=400, shop=shop)
    session.add_all([shop, owner])
    prices = {"Rice": 60, "Toor dal": 150, "Poha": 90, "Sago": 110, "Sugar": 55, "Saffron": None}
    items = {name: Item(name=name, unit="kg", pack_size="1 kg", price_inr=p) for name, p in prices.items()}
    session.add_all(items.values())
    session.flush()
    straps = {}
    for n, name in enumerate(["Rice", "Toor dal", "Poha", "Sago"], start=1):
        device_id = f"sb-DEMO{n:08d}"
        token = f"token-{n}"
        session.add(Strap(device_id=device_id, owner_id=owner.id, display_name=f"{name} jar",
                          item_id=items[name].id, device_token_hash=hash_token(token), state=StrapState.OK,
                          state_since=T0, last_seen=T0, baseline=800.0, gap=35.0, rssi=-50))
        straps[name] = {"device_id": device_id,
                        "headers": {"Authorization": f"Bearer {token}", "X-Device-Id": device_id}}
    session.commit()
    return {"owner_id": owner.id, "shop_id": shop.id, "items": {k: v.id for k, v in items.items()},
            "straps": straps}
