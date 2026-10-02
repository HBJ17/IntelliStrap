from app import clock
from app.models import Event, EventType, Strap, StrapState
from app.security import CLAIM_ALPHABET
from tests.conftest import T0


def send(client, headers, event_type, payload):
    return client.post("/api/device/events", headers=headers, json={"type": event_type, "payload": payload})


def test_register_returns_token_and_claim_code(register, session):
    data = register()
    assert len(data["device_token"]) == 64
    code = data["claim_code"]
    assert len(code) == 6 and set(code) <= set(CLAIM_ALPHABET)
    strap = session.get(Strap, "sb-TEST00000001")
    assert strap.state == StrapState.UNKNOWN
    assert strap.device_token_hash != data["device_token"]  # only the hash is stored


def test_register_rejects_bad_secret_and_bad_id(client):
    r = client.post("/api/device/register", json={"device_id": "sb-TEST00000001", "provision_secret": "nope"})
    assert r.status_code == 401
    r = client.post("/api/device/register", json={"device_id": "../etc", "provision_secret": "test-provision"})
    assert r.status_code == 422


def test_reregister_rotates_token_and_keeps_name(register, client, session):
    first = register()
    strap = session.get(Strap, "sb-TEST00000001")
    strap.display_name = "Rice jar"
    strap.owner_id = None
    session.commit()
    second = register()
    assert second["device_token"] != first["device_token"]
    assert send(client, first["headers"], "heartbeat", {}).status_code == 401
    assert send(client, second["headers"], "heartbeat", {}).status_code == 200
    session.expire_all()
    assert session.get(Strap, "sb-TEST00000001").display_name == "Rice jar"


def test_unknown_device_and_bad_token_rejected_and_nothing_stored(register, client, session):
    dev = register()
    r = send(client, {"Authorization": "Bearer " + "0" * 64, "X-Device-Id": "sb-TEST00000001"},
             "heartbeat", {})
    assert r.status_code == 401
    r = send(client, {"Authorization": f"Bearer {dev['device_token']}", "X-Device-Id": "sb-NOPE00000000"},
             "heartbeat", {})
    assert r.status_code == 401
    r = send(client, {}, "heartbeat", {})
    assert r.status_code == 401
    assert session.query(Event).count() == 0


def test_r1_state_changes_logged_with_server_timestamp(register, client, session):
    dev = register()
    r = send(client, dev["headers"], "state_change", {"state": "LOW", "gap": 12.4, "baseline": 811.2})
    assert r.json() == {"ok": True, "stored": True, "commands": []}
    clock.advance(minutes=5)
    send(client, dev["headers"], "state_change", {"state": "OK", "gap": 30.0, "baseline": 811.0})

    events = session.query(Event).order_by(Event.id).all()
    assert [e.type for e in events] == [EventType.state_change, EventType.state_change]
    assert events[0].ts == T0 and events[0].value == {"state": "LOW", "gap": 12.4, "baseline": 811.2}
    assert events[1].ts == clock.now()
    strap = session.get(Strap, "sb-TEST00000001")
    assert strap.state == StrapState.OK and strap.state_since == clock.now()
    assert strap.gap == 30.0 and strap.last_seen == clock.now()


def test_repeat_low_does_not_reset_state_since(register, client, session):
    dev = register()
    send(client, dev["headers"], "state_change", {"state": "LOW"})
    clock.advance(minutes=3)
    send(client, dev["headers"], "state_change", {"state": "LOW"})
    assert session.get(Strap, "sb-TEST00000001").state_since == T0


def test_device_timestamp_is_not_accepted(register, client):
    dev = register()
    r = client.post("/api/device/events", headers=dev["headers"],
                    json={"type": "heartbeat", "payload": {}, "ts": "2020-01-01T00:00:00Z"})
    assert r.status_code == 422


def test_recalibration_always_logged(register, client, session):
    dev = register()
    for baseline in (800.0, 801.0, 802.0):
        assert send(client, dev["headers"], "recalibration", {"baseline": baseline}).json()["stored"]
    rows = session.query(Event).filter(Event.type == EventType.recalibration).all()
    assert [r.value["baseline"] for r in rows] == [800.0, 801.0, 802.0]
    assert session.get(Strap, "sb-TEST00000001").baseline == 802.0


def test_drift_throttled_per_device(register, client, session):
    dev = register()
    assert send(client, dev["headers"], "baseline_drift", {"baseline": 800.0}).json()["stored"]
    clock.advance(minutes=5)
    assert not send(client, dev["headers"], "baseline_drift", {"baseline": 801.0}).json()["stored"]
    clock.advance(minutes=11)
    assert send(client, dev["headers"], "baseline_drift", {"baseline": 802.0}).json()["stored"]
    assert session.query(Event).filter(Event.type == EventType.baseline_drift).count() == 2
    # The dropped event still refreshed the strap's latest baseline.
    assert session.get(Strap, "sb-TEST00000001").baseline == 802.0


def test_invalid_payload_rejected(register, client, session):
    dev = register()
    assert send(client, dev["headers"], "state_change", {"state": "FULL"}).status_code == 422
    assert send(client, dev["headers"], "recalibration", {}).status_code == 422
    assert send(client, dev["headers"], "heartbeat", {"rssi": 50}).status_code == 422
    assert send(client, dev["headers"], "nonsense", {}).status_code == 422
    assert session.query(Event).count() == 0


def test_heartbeat_updates_rssi(register, client, session):
    dev = register()
    send(client, dev["headers"], "heartbeat", {"gap": 30.0, "baseline": 805.0, "rssi": -61, "uptime_s": 99})
    strap = session.get(Strap, "sb-TEST00000001")
    assert strap.rssi == -61 and strap.baseline == 805.0


def test_pending_command_delivered_once(register, client, session):
    dev = register()
    strap = session.get(Strap, "sb-TEST00000001")
    strap.pending_command = "recalibrate"
    session.commit()
    assert send(client, dev["headers"], "heartbeat", {}).json()["commands"] == ["recalibrate"]
    assert client.get("/api/device/commands", headers=dev["headers"]).json() == {"commands": []}
