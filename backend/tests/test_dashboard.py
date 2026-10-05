from app import clock
from app.models import Strap


def test_dashboard_requires_login(client):
    assert client.get("/api/straps").status_code == 401
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    assert client.get("/api/me").json()["authenticated"] is False
    assert client.post("/api/login", json={"password": "test-password"}).status_code == 200
    assert client.get("/api/me").json()["authenticated"] is True
    assert client.get("/api/straps").status_code == 200


def test_forged_session_cookie_rejected(client):
    client.cookies.set("sb_session", "eyJ1Ijoib3duZXIifQ.forged.sig")
    assert client.get("/api/straps").status_code == 401


def test_list_straps_with_computed_status(auth_client, demo):
    straps = {s["display_name"]: s for s in auth_client.get("/api/straps").json()}
    assert straps["Rice jar"]["status"] == "OK"
    assert straps["Rice jar"]["item"]["name"] == "Rice"
    assert straps["Rice jar"]["fill_pct"] == 88  # gap 35 of 40


def test_r10_silent_strap_shows_offline_not_last_state(auth_client, demo, client):
    rice = demo["straps"]["Rice"]
    client.post("/api/device/events", headers=rice["headers"],
                json={"type": "state_change", "payload": {"state": "OK"}})
    clock.advance(minutes=16)
    straps = {s["device_id"]: s for s in auth_client.get("/api/straps").json()}
    assert straps[rice["device_id"]]["status"] == "OFFLINE"
    assert straps[rice["device_id"]]["state"] == "OK"  # stored state untouched


def test_never_reported_strap_is_unknown(auth_client, register, demo):
    dev = register("sb-NEW000000002")
    auth_client.post("/api/straps/claim", json={"claim_code": dev["claim_code"], "display_name": "New"})
    straps = {s["device_id"]: s for s in auth_client.get("/api/straps").json()}
    assert straps["sb-NEW000000002"]["status"] == "UNKNOWN"


def test_claim_flow(auth_client, register, demo, session):
    dev = register("sb-NEW000000001")
    r = auth_client.post("/api/straps/claim", json={"claim_code": dev["claim_code"].lower(),
                                                    "display_name": "Sugar tin", "item_id": demo["items"]["Sugar"]})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["name"] == "Sugar"
    strap = session.get(Strap, "sb-NEW000000001")
    assert strap.claim_code is None and strap.owner_id == demo["owner_id"]
    # A used code cannot be claimed again.
    r = auth_client.post("/api/straps/claim", json={"claim_code": dev["claim_code"], "display_name": "x"})
    assert r.status_code == 404


def test_rename_persists_across_reboot(auth_client, demo, client):
    rice = demo["straps"]["Rice"]
    r = auth_client.patch(f"/api/straps/{rice['device_id']}", json={"display_name": "Basmati"})
    assert r.json()["display_name"] == "Basmati"
    # Strap "reboots" and re-registers; the name lives in the backend, so it survives.
    client.post("/api/device/register", json={"device_id": rice["device_id"], "provision_secret": "test-provision"})
    names = [s["display_name"] for s in auth_client.get("/api/straps").json()]
    assert "Basmati" in names


def test_patch_item_and_clear(auth_client, demo):
    rice = demo["straps"]["Rice"]["device_id"]
    r = auth_client.patch(f"/api/straps/{rice}", json={"item_id": demo["items"]["Sugar"]})
    assert r.json()["item"]["name"] == "Sugar"
    r = auth_client.patch(f"/api/straps/{rice}", json={"item_id": None})
    assert r.json()["item"] is None
    assert auth_client.patch(f"/api/straps/{rice}", json={"item_id": 9999}).status_code == 404
    assert auth_client.patch("/api/straps/sb-NOPE00000000", json={"display_name": "x"}).status_code == 404


def test_recalibrate_command_reaches_strap(auth_client, demo, client):
    rice = demo["straps"]["Rice"]
    assert auth_client.post(f"/api/straps/{rice['device_id']}/recalibrate").status_code == 200
    r = client.post("/api/device/events", headers=rice["headers"], json={"type": "heartbeat", "payload": {}})
    assert r.json()["commands"] == ["recalibrate"]


def test_history_timeline(auth_client, demo, client):
    rice = demo["straps"]["Rice"]
    for event_type, payload in [("state_change", {"state": "LOW"}), ("state_change", {"state": "OK"}),
                                ("recalibration", {"baseline": 790.5}), ("heartbeat", {})]:
        client.post("/api/device/events", headers=rice["headers"], json={"type": event_type, "payload": payload})
        clock.advance(minutes=1)
    entries = auth_client.get(f"/api/history/{rice['device_id']}").json()["entries"]
    assert [e["kind"] for e in entries] == ["recalibration", "refill", "state_low"]
    assert entries[0]["baseline"] == 790.5


def test_settings_roundtrip(auth_client, demo):
    s = auth_client.get("/api/settings").json()
    assert s["owner"]["list_threshold_inr"] == 400 and s["global"]["hold_seconds"] == 20
    r = auth_client.put("/api/settings", json={
        "owner": {"whatsapp_number": "+919876543210", "list_threshold_inr": 500},
        "shop": {"opted_in": False},
        "global": {"hold_seconds": 5}})
    assert r.status_code == 200, r.text
    s = auth_client.get("/api/settings").json()
    assert s["owner"]["whatsapp_number"] == "+919876543210"
    assert s["owner"]["list_threshold_inr"] == 500
    assert s["shop"]["opted_in"] is False and s["global"]["hold_seconds"] == 5
    assert auth_client.put("/api/settings", json={"owner": {"whatsapp_number": "98765"}}).status_code == 422


def test_catalog_crud(auth_client, demo):
    r = auth_client.post("/api/items", json={"name": "Ghee", "unit": "l", "pack_size": "500 ml", "price_inr": 320})
    assert r.status_code == 201
    item_id = r.json()["id"]
    r = auth_client.put(f"/api/items/{item_id}", json={"name": "Ghee", "price_inr": 330})
    assert r.json()["price_inr"] == 330
    assert auth_client.delete(f"/api/items/{item_id}").status_code == 200
    assert all(i["name"] != "Ghee" for i in auth_client.get("/api/items").json())


def test_edit_label_free_text(auth_client, demo, session):
    from app.models import Item
    rice = demo["straps"]["Rice"]["device_id"]
    # Existing catalog item, matched case-insensitively.
    r = auth_client.patch(f"/api/straps/{rice}", json={"label": "  sugar "})
    assert r.json()["item"]["id"] == demo["items"]["Sugar"]
    # New label is added to the catalog without a price (never counted as Rs 0).
    r = auth_client.patch(f"/api/straps/{rice}", json={"label": "Basmati  rice"})
    assert r.json()["item"]["name"] == "Basmati rice" and r.json()["item"]["price_inr"] is None
    assert session.query(Item).filter(Item.name == "Basmati rice").count() == 1
    auth_client.patch(f"/api/straps/{rice}", json={"label": "basmati rice"})
    assert session.query(Item).filter(Item.name.ilike("basmati rice")).count() == 1
    # Empty label clears it.
    assert auth_client.patch(f"/api/straps/{rice}", json={"label": ""}).json()["item"] is None


def test_claim_with_new_label(auth_client, register, demo):
    dev = register("sb-NEW000000003")
    r = auth_client.post("/api/straps/claim", json={"claim_code": dev["claim_code"], "display_name": "Tin",
                                                    "label": "Jaggery"})
    assert r.status_code == 200 and r.json()["item"]["name"] == "Jaggery"


def test_renaming_catalog_item_renames_label_everywhere(auth_client, demo):
    auth_client.put(f"/api/items/{demo['items']['Toor dal']}", json={"name": "Arhar dal", "price_inr": 150})
    names = {s["display_name"]: s["item"]["name"] for s in auth_client.get("/api/straps").json()}
    assert names["Toor dal jar"] == "Arhar dal"


def test_set_label_with_price(auth_client, demo, session):
    from app.models import Item
    rice = demo["straps"]["Rice"]["device_id"]
    r = auth_client.patch(f"/api/straps/{rice}", json={"label": "Basmati rice", "price_inr": 140})
    assert r.json()["item"] == {**r.json()["item"], "name": "Basmati rice", "price_inr": 140}
    # Changing only the price updates the catalog item.
    r = auth_client.patch(f"/api/straps/{rice}", json={"price_inr": 150})
    assert r.json()["item"]["price_inr"] == 150
    assert session.query(Item).filter_by(name="Basmati rice").one().price_inr == 150
    # A price without a label is refused.
    auth_client.patch(f"/api/straps/{rice}", json={"label": ""})
    assert auth_client.patch(f"/api/straps/{rice}", json={"price_inr": 10}).status_code == 422


def test_claim_with_label_and_price(auth_client, register, demo):
    dev = register("sb-NEW000000004")
    r = auth_client.post("/api/straps/claim", json={"claim_code": dev["claim_code"], "display_name": "Tea tin",
                                                    "label": "Masala tea", "price_inr": 180})
    assert r.json()["item"]["price_inr"] == 180


def test_price_fills_unpriced_list_row(auth_client, demo):
    auth_client.post("/api/list/items", json={"item_id": demo["items"]["Saffron"]})
    sago = demo["straps"]["Sago"]["device_id"]
    auth_client.patch(f"/api/straps/{sago}", json={"label": "Saffron", "price_inr": 250})
    data = auth_client.get("/api/list").json()
    assert data["missing_prices"] == [] and data["total_inr"] == 250


def test_delete_strap_and_add_it_back(auth_client, demo, client, session):
    from app.models import Event, ListItem, ListStatus, Strap
    rice = demo["straps"]["Rice"]
    client.post("/api/device/events", headers=rice["headers"], json={"type": "state_change", "payload": {"state": "LOW"}})
    auth_client.post("/api/list/items", json={"strap_id": rice["device_id"]})

    assert auth_client.delete(f"/api/straps/{rice['device_id']}").status_code == 200
    session.expire_all()
    assert session.get(Strap, rice["device_id"]) is None
    assert session.query(Event).count() == 0
    [row] = session.query(ListItem).all()
    assert row.status == ListStatus.cancelled and row.strap_id is None
    assert all(s["device_id"] != rice["device_id"] for s in auth_client.get("/api/straps").json())

    # The strap's old token stops working; it registers again and gets a new claim code.
    r = client.post("/api/device/events", headers=rice["headers"], json={"type": "heartbeat", "payload": {}})
    assert r.status_code == 401
    reg = client.post("/api/device/register", json={"device_id": rice["device_id"],
                                                      "provision_secret": "test-provision"}).json()
    r = auth_client.post("/api/straps/claim", json={"claim_code": reg["claim_code"], "display_name": "Rice again",
                                                    "label": "Rice"})
    assert r.status_code == 200
    assert auth_client.delete("/api/straps/sb-NOPE00000000").status_code == 404


def test_recent_events_stream(auth_client, demo, client):
    rice, sago = demo["straps"]["Rice"], demo["straps"]["Sago"]
    for strap, event_type, payload in [(rice, "state_change", {"state": "LOW", "gap": 8.0}),
                                       (rice, "heartbeat", {}),
                                       (sago, "recalibration", {"baseline": 790.0}),
                                       (rice, "state_change", {"state": "OK"})]:
        client.post("/api/device/events", headers=strap["headers"], json={"type": event_type, "payload": payload})
        clock.advance(seconds=10)
    events = auth_client.get("/api/events/recent").json()
    assert [(e["strap_name"], e["kind"]) for e in events] == [
        ("Rice jar", "ok"), ("Sago jar", "recalibration"), ("Rice jar", "low")]
    assert events[2]["gap"] == 8.0 and events[1]["baseline"] == 790.0
    assert len(auth_client.get("/api/events/recent?limit=1").json()) == 1
