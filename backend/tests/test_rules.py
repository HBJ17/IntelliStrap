"""Rules R2-R10, R13, R14 with a controllable clock (no sleeping)."""
from datetime import timedelta

from app import clock, rules, scheduler
from app.messaging import ParsedReply, format_items_inline
from app.models import Event, EventType, Item, ListItem, ListStatus, Order, OrderStatus, Owner, Shop, Strap


def go_low(strap_event, strap):
    strap_event(strap, "state_change", {"state": "LOW", "gap": 8.0, "baseline": 800.0})


def go_ok(strap_event, strap):
    strap_event(strap, "state_change", {"state": "OK", "gap": 35.0, "baseline": 800.0})


def heartbeat_all(strap_event, demo):
    for s in demo["straps"].values():
        strap_event(s, "heartbeat", {"rssi": -50})


def rows(session, **filters):
    session.expire_all()
    return session.query(ListItem).filter_by(**filters).order_by(ListItem.id).all()


def wait_hold(strap_event, demo, minutes=21):
    """Advance past the hold time while the straps keep reporting (so none look offline)."""
    for _ in range(minutes // 7):
        clock.advance(minutes=7)
        heartbeat_all(strap_event, demo)
    clock.advance(minutes=minutes % 7)
    scheduler.run_frequent()


# --- R2 / R3 / R4 --------------------------------------------------------------------

def test_r2_nothing_added_during_hold(demo, strap_event, session):
    go_low(strap_event, demo["straps"]["Rice"])
    clock.advance(seconds=19)
    scheduler.run_frequent()
    assert rows(session) == []


def test_r2_back_to_ok_within_hold_adds_nothing(demo, strap_event, session):
    rice = demo["straps"]["Rice"]
    go_low(strap_event, rice)
    clock.advance(seconds=10)
    go_ok(strap_event, rice)
    wait_hold(strap_event, demo, minutes=30)
    assert rows(session) == []


def test_r3_still_low_after_hold_is_added_with_price(demo, strap_event, session):
    go_low(strap_event, demo["straps"]["Toor dal"])
    wait_hold(strap_event, demo)
    [row] = rows(session)
    assert row.status == ListStatus.pending and row.qty == 1
    assert row.price_at_time_inr == 150 and row.strap_id == demo["straps"]["Toor dal"]["device_id"]


def test_r3_unlabelled_or_unclaimed_strap_not_added(demo, strap_event, session):
    rice = session.get(Strap, demo["straps"]["Rice"]["device_id"])
    rice.item_id = None
    poha = session.get(Strap, demo["straps"]["Poha"]["device_id"])
    poha.owner_id = None
    session.commit()
    go_low(strap_event, demo["straps"]["Rice"])
    go_low(strap_event, demo["straps"]["Poha"])
    wait_hold(strap_event, demo)
    assert rows(session) == []


def test_r4_repeat_low_never_duplicates(demo, strap_event, session):
    rice = demo["straps"]["Rice"]
    go_low(strap_event, rice)
    wait_hold(strap_event, demo)
    for _ in range(3):
        go_low(strap_event, rice)
        clock.advance(minutes=25)
        go_low(strap_event, rice)
        scheduler.run_frequent()
    assert len(rows(session)) == 1


def test_r4_partial_unique_index_enforced(demo, session):
    from sqlalchemy.exc import IntegrityError
    import pytest

    strap_id = demo["straps"]["Rice"]["device_id"]
    for _ in range(2):
        session.add(ListItem(owner_id=demo["owner_id"], strap_id=strap_id, item_id=demo["items"]["Rice"],
                             qty=1, price_at_time_inr=60, status=ListStatus.pending, added_at=clock.now()))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- R5 --------------------------------------------------------------------------------

def test_r5_refill_cancels_pending_row(demo, strap_event, session):
    rice = demo["straps"]["Rice"]
    go_low(strap_event, rice)
    wait_hold(strap_event, demo)
    go_ok(strap_event, rice)
    [row] = rows(session)
    assert row.status == ListStatus.cancelled
    assert rules.list_summary(session, session.get(Owner, demo["owner_id"]))["rows"] == []


def test_r5_refill_marks_ordered_row_fulfilled(demo, strap_event, session):
    for name in ["Rice", "Toor dal", "Poha", "Sago"]:
        go_low(strap_event, demo["straps"][name])
    wait_hold(strap_event, demo)
    go_ok(strap_event, demo["straps"]["Rice"])
    statuses = {r.item.name: r.status for r in rows(session)}
    assert statuses["Rice"] == ListStatus.fulfilled
    assert statuses["Sago"] == ListStatus.ordered


# --- R6 / R7 ---------------------------------------------------------------------------

def test_r6_four_jars_trigger_exactly_one_order(demo, strap_event, session, sim):
    for name in ["Rice", "Toor dal", "Poha", "Sago"]:
        go_low(strap_event, demo["straps"][name])
        clock.advance(seconds=30)
    wait_hold(strap_event, demo)
    wait_hold(strap_event, demo)  # later passes must not create more orders

    [order] = session.query(Order).all()
    assert order.total_inr == 410 and order.status == OrderStatus.awaiting_owner
    assert all(r.status == ListStatus.ordered and r.order_id == order.id for r in rows(session))
    owner_msgs = [m for m in sim.messages if m["role"] == "owner_list"]
    assert len(owner_msgs) == 1
    assert owner_msgs[0]["to"] == "+919000000001"
    assert "₹410" in owner_msgs[0]["text"]
    assert [b["payload"] for b in owner_msgs[0]["buttons"]] == [f"order:{order.id}:yes", f"order:{order.id}:no"]


def test_r6_below_threshold_waits(demo, strap_event, session):
    for name in ["Rice", "Toor dal", "Poha"]:  # 300
        go_low(strap_event, demo["straps"][name])
    wait_hold(strap_event, demo)
    assert session.query(Order).count() == 0
    assert len(rows(session, status=ListStatus.pending)) == 3


def test_r7_new_low_after_order_starts_next_list(demo, strap_event, session, auth_client):
    for name in ["Rice", "Toor dal", "Poha", "Sago"]:
        go_low(strap_event, demo["straps"][name])
    wait_hold(strap_event, demo)
    r = auth_client.post("/api/list/items", json={"item_id": demo["items"]["Sugar"]})
    assert r.status_code == 201
    data = auth_client.get("/api/list").json()
    assert [row["item_name"] for row in data["rows"]] == ["Sugar"]
    assert data["total_inr"] == 55 and session.query(Order).count() == 1


# --- R8 ---------------------------------------------------------------------------------

def test_r8_manual_add_remove_and_send_now(demo, auth_client, session, sim):
    assert auth_client.post("/api/list/send").status_code == 409  # empty list
    r = auth_client.post("/api/list/items", json={"strap_id": demo["straps"]["Rice"]["device_id"]})
    assert r.status_code == 201
    # The same strap cannot be listed twice (R4).
    assert auth_client.post("/api/list/items", json={"strap_id": demo["straps"]["Rice"]["device_id"]}).status_code == 409
    r = auth_client.post("/api/list/items", json={"item_id": demo["items"]["Sugar"]})
    sugar_row = [row for row in r.json()["rows"] if row["item_name"] == "Sugar"][0]
    r = auth_client.delete(f"/api/list/items/{sugar_row['id']}")
    assert [row["item_name"] for row in r.json()["rows"]] == ["Rice"]

    r = auth_client.post("/api/list/send")
    assert r.status_code == 200, r.text
    assert r.json()["total_inr"] == 60 and r.json()["status"] == "awaiting_owner"
    assert len([m for m in sim.messages if m["role"] == "owner_list"]) == 1
    # Ordered rows can no longer be removed.
    rice_row = rows(session, status=ListStatus.ordered)[0]
    assert auth_client.delete(f"/api/list/items/{rice_row.id}").status_code == 409


# --- R9 ---------------------------------------------------------------------------------

def test_r9_missing_price_excluded_and_blocks_send(demo, auth_client, session):
    auth_client.post("/api/list/items", json={"item_id": demo["items"]["Saffron"]})
    auth_client.post("/api/list/items", json={"item_id": demo["items"]["Rice"]})
    data = auth_client.get("/api/list").json()
    assert data["total_inr"] == 60
    assert data["missing_prices"] == [{"item_id": demo["items"]["Saffron"], "name": "Saffron"}]
    assert [r["needs_price"] for r in data["rows"]] == [True, False]
    r = auth_client.post("/api/list/send")
    assert r.status_code == 409 and "Saffron" in r.json()["detail"]
    assert session.query(Order).count() == 0


def test_r9_threshold_order_never_contains_unpriced_item(demo, auth_client, session, sim):
    auth_client.post("/api/list/items", json={"item_id": demo["items"]["Saffron"]})
    for name in ["Rice", "Toor dal", "Poha", "Sago"]:
        auth_client.post("/api/list/items", json={"item_id": demo["items"][name]})
    [order] = session.query(Order).all()
    assert order.total_inr == 410
    assert "Saffron" not in format_items_inline(order.rows)
    assert [r.item.name for r in rows(session, status=ListStatus.pending)] == ["Saffron"]


def test_r9_entering_price_fills_pending_rows(demo, auth_client):
    auth_client.post("/api/list/items", json={"item_id": demo["items"]["Saffron"]})
    auth_client.put(f"/api/items/{demo['items']['Saffron']}", json={"name": "Saffron", "price_inr": 250})
    data = auth_client.get("/api/list").json()
    assert data["missing_prices"] == [] and data["total_inr"] == 250


# --- R10 --------------------------------------------------------------------------------

def test_r10_offline_strap_never_added(demo, strap_event, session):
    go_low(strap_event, demo["straps"]["Rice"])
    clock.advance(minutes=25)  # silent for longer than offline_minutes
    scheduler.run_frequent()
    assert rows(session) == []


# --- R13 --------------------------------------------------------------------------------

def test_r13_pruning_keeps_state_changes_and_recalibrations(demo, strap_event, session):
    rice = demo["straps"]["Rice"]
    for event_type, payload in [("heartbeat", {}), ("baseline_drift", {"baseline": 801.0}),
                                ("state_change", {"state": "LOW"}), ("recalibration", {"baseline": 799.0})]:
        strap_event(rice, event_type, payload)
    clock.advance(days=31)
    strap_event(rice, "heartbeat", {})
    removed = scheduler.prune_events(session, clock.now())
    session.commit()
    assert removed == 2
    kinds = sorted(e.type.value for e in session.query(Event))
    assert kinds == ["heartbeat", "recalibration", "state_change"]


# --- order replies (R14) ---------------------------------------------------------------

def make_order(demo, auth_client, session) -> Order:
    for name in ["Rice", "Toor dal", "Poha", "Sago"]:
        auth_client.post("/api/list/items", json={"item_id": demo["items"][name]})
    return session.query(Order).one()


def test_order_reply_sends_to_shop_once(demo, auth_client, session, sim):
    order = make_order(demo, auth_client, session)
    r1 = auth_client.post("/api/sim/reply", json={"order_id": order.id, "action": "order"})
    r2 = auth_client.post("/api/sim/reply", json={"order_id": order.id, "action": "order"})
    assert r1.json()["outcome"] == "sent_to_shop"
    assert r2.json()["outcome"] == "already_handled"
    shop_msgs = [m for m in sim.messages if m["role"] == "shop_order"]
    assert len(shop_msgs) == 1
    assert shop_msgs[0]["to"] == "+919000000002"
    assert shop_msgs[0]["text"] == ("New order from Asha: Rice ×1 ₹60, Toor dal ×1 ₹150, Poha ×1 ₹90, "
                                    "Sago ×1 ₹110. Total ₹410. Please confirm delivery.")
    texts = [m["text"] for m in sim.messages if m["role"] == "text"]
    assert texts[0] == "Sent to Corner Shop." and "already handled" in texts[1]
    session.expire_all()
    assert order.status == OrderStatus.sent_to_shop and order.sent_to_shop_at == clock.now()
    assert {m["role"] for m in order.twilio_message_ids} == {"owner", "shop"}


def test_not_now_cancels_and_returns_rows(demo, auth_client, session, sim):
    order = make_order(demo, auth_client, session)
    r = auth_client.post("/api/sim/reply", json={"order_id": order.id, "action": "not_now"})
    assert r.json()["outcome"] == "cancelled"
    session.expire_all()
    assert order.status == OrderStatus.cancelled
    assert len(rows(session, status=ListStatus.pending)) == 4
    # A late "Order" tap on the cancelled order does nothing.
    r = auth_client.post("/api/sim/reply", json={"order_id": order.id, "action": "order"})
    assert r.json()["outcome"] == "already_handled"
    assert not [m for m in sim.messages if m["role"] == "shop_order"]


def test_keyword_reply_ties_to_latest_open_order(demo, auth_client, session, sim):
    order = make_order(demo, auth_client, session)
    outcome = rules.handle_reply(session, ParsedReply("order", None, "+919000000001"), clock.now(), sim)
    assert outcome == "sent_to_shop"
    assert rules.handle_reply(session, ParsedReply("order", None, "+910000000000"), clock.now(), sim) \
        == "unknown_sender"
    assert rules.handle_reply(session, ParsedReply("order", order.id, "+910000000000"), clock.now(), sim) \
        == "unknown_sender"


def test_shop_not_opted_in_fails_and_is_retryable(demo, auth_client, session, sim):
    shop = session.get(Shop, demo["shop_id"])
    shop.opted_in = False
    session.commit()
    order = make_order(demo, auth_client, session)
    r = auth_client.post("/api/sim/reply", json={"order_id": order.id, "action": "order"})
    assert r.json()["outcome"] == "send_failed"
    orders = auth_client.get("/api/orders").json()
    assert orders[0]["unsent"] is True and "opted in" in orders[0]["last_error"]
    assert any("Could not send" in m["text"] for m in sim.messages if m["role"] == "text")

    auth_client.put("/api/settings", json={"shop": {"opted_in": True}})
    r = auth_client.post(f"/api/orders/{order.id}/retry")
    assert r.status_code == 200 and r.json()["status"] == "sent_to_shop"
    assert len([m for m in sim.messages if m["role"] == "shop_order"]) == 1


def test_owner_send_failure_marks_unsent_and_retry(demo, auth_client, session, sim):
    sim.fail_roles.add("owner_list")
    order = make_order(demo, auth_client, session)
    session.expire_all()
    assert order.status == OrderStatus.send_failed and order.owner_sent_at is None
    sim.fail_roles.clear()
    r = auth_client.post(f"/api/orders/{order.id}/retry")
    assert r.json()["status"] == "awaiting_owner"


def test_cancel_unsent_order_from_dashboard(demo, auth_client, session, sim):
    sim.fail_roles.add("owner_list")
    order = make_order(demo, auth_client, session)
    assert auth_client.post(f"/api/orders/{order.id}/cancel").json()["status"] == "cancelled"
    assert len(rows(session, status=ListStatus.pending)) == 4


def test_fast_forward_and_sim_event(demo, auth_client, session):
    r = auth_client.post("/api/sim/event", json={"device_id": demo["straps"]["Rice"]["device_id"],
                                                 "type": "state_change", "payload": {"state": "LOW"}})
    assert r.status_code == 200
    assert auth_client.post("/api/sim/fast-forward").json() == {"added": 1}


def test_format_items_inline():
    def row(name, qty, price):
        return ListItem(item=Item(name=name), qty=qty, price_at_time_inr=price)
    rows_ = [row("Rice", 1, 60), row("Toor dal", 1, 150), row("Poha", 1, 90), row("Sago", 1, 110)]
    assert format_items_inline(rows_) == "Rice ×1 ₹60, Toor dal ×1 ₹150, Poha ×1 ₹90, Sago ×1 ₹110"
    assert format_items_inline([row("Sugar", 2, 55)]) == "Sugar ×2 ₹110"


def test_dev_hold_seconds_overrides_setting(demo, session, monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("DEV_HOLD_SECONDS", "10")
    get_settings.cache_clear()
    assert rules.hold_delta(session) == timedelta(seconds=10)
