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
from app.models import Base  # noqa: E402

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fresh_state():
    get_settings.cache_clear()
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
