from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock, rules, settings_store
from ..config import get_settings
from ..db import get_db
from ..models import Event, EventType, Item, ListItem, ListStatus, Order, Shop, Strap, StrapState
from ..schemas import ClaimRequest, ItemIn, ListAdd, LoginRequest, SettingsUpdate, StrapPatch
from ..security import (SESSION_COOKIE, SESSION_MAX_AGE, constant_eq, make_session_token, require_dashboard,
                        session_valid)

public = APIRouter(prefix="/api", tags=["auth"])
router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(require_dashboard)])


# --- auth --------------------------------------------------------------------

@public.post("/login")
def login(body: LoginRequest, response: Response):
    settings = get_settings()
    if not constant_eq(body.password, settings.dashboard_password):
        raise HTTPException(401, "wrong password")
    response.set_cookie(SESSION_COOKIE, make_session_token(), max_age=SESSION_MAX_AGE, httponly=True,
                        samesite="lax", secure=not settings.is_dev)
    return {"ok": True}


@public.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@public.get("/me")
def me(request: Request):
    settings = get_settings()
    return {"authenticated": session_valid(request.cookies.get(SESSION_COOKIE)),
            "messaging_mode": settings.messaging_mode, "dev": settings.is_dev}


# --- serialisers -------------------------------------------------------------

def item_out(item: Item | None) -> dict | None:
    if item is None:
        return None
    return {"id": item.id, "name": item.name, "unit": item.unit, "pack_size": item.pack_size,
            "price_inr": item.price_inr}


def strap_out(strap: Strap, now: datetime, cfg: dict[str, int]) -> dict:
    fill = None
    if strap.gap is not None:
        fill = max(0, min(100, round(strap.gap / cfg["fill_gap_full"] * 100)))
    return {
        "device_id": strap.device_id,
        "display_name": strap.display_name,
        "item": item_out(strap.item),
        "status": rules.strap_status(strap, now, cfg["offline_minutes"]),
        "state": strap.state.value,
        "state_since": strap.state_since,
        "fill_pct": fill,
        "gap": strap.gap,
        "baseline": strap.baseline,
        "rssi": strap.rssi,
        "last_seen": strap.last_seen,
        "pending_command": strap.pending_command,
    }


def owned_strap(db: Session, device_id: str) -> Strap:
    owner = rules.get_owner(db)
    strap = db.get(Strap, device_id)
    if strap is None or strap.owner_id != owner.id:
        raise HTTPException(404, "strap not found")
    return strap


def get_item_or_404(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    return item


# --- straps ------------------------------------------------------------------

@router.get("/straps")
def list_straps(db: Session = Depends(get_db)):
    owner = rules.get_owner(db)
    cfg = settings_store.get_all(db)
    now = clock.now()
    straps = db.scalars(select(Strap).where(Strap.owner_id == owner.id).order_by(Strap.display_name)).all()
    db.commit()
    return [strap_out(s, now, cfg) for s in straps]


@router.post("/straps/claim")
def claim_strap(body: ClaimRequest, db: Session = Depends(get_db)):
    owner = rules.get_owner(db)
    strap = db.scalars(select(Strap).where(Strap.claim_code == body.claim_code.upper(),
                                           Strap.owner_id.is_(None))).first()
    if strap is None:
        raise HTTPException(404, "no unclaimed strap with that code")
    if body.item_id is not None:
        get_item_or_404(db, body.item_id)
    strap.owner_id = owner.id
    strap.display_name = body.display_name.strip()
    strap.item_id = body.item_id
    strap.claim_code = None
    db.commit()
    return strap_out(strap, clock.now(), settings_store.get_all(db))


@router.patch("/straps/{device_id}")
def patch_strap(device_id: str, body: StrapPatch, db: Session = Depends(get_db)):
    strap = owned_strap(db, device_id)
    if "display_name" in body.model_fields_set:
        if not body.display_name:
            raise HTTPException(422, "display_name cannot be empty")
        strap.display_name = body.display_name.strip()
    if "item_id" in body.model_fields_set:
        if body.item_id is not None:
            get_item_or_404(db, body.item_id)
        strap.item_id = body.item_id
    db.commit()
    db.refresh(strap)
    return strap_out(strap, clock.now(), settings_store.get_all(db))


@router.post("/straps/{device_id}/recalibrate")
def recalibrate(device_id: str, db: Session = Depends(get_db)):
    strap = owned_strap(db, device_id)
    strap.pending_command = "recalibrate"
    db.commit()
    return {"ok": True, "pending_command": strap.pending_command}


@router.get("/history/{device_id}")
def history(device_id: str, limit: int = 100, db: Session = Depends(get_db)):
    strap = owned_strap(db, device_id)
    limit = max(1, min(limit, 500))
    events = db.scalars(
        select(Event)
        .where(Event.device_id == strap.device_id,
               Event.type.in_([EventType.state_change, EventType.recalibration]))
        .order_by(Event.ts.desc(), Event.id.desc())
        .limit(limit)
    ).all()

    entries: list[dict] = []
    prev_state: str | None = None
    for e in reversed(events):
        if e.type == EventType.recalibration:
            entries.append({"ts": e.ts, "kind": "recalibration", "baseline": e.value.get("baseline"),
                            "text": f"Recalibrated (baseline {e.value.get('baseline')})"})
            continue
        state = e.value.get("state")
        if state == StrapState.OK.value and prev_state == StrapState.LOW.value:
            entries.append({"ts": e.ts, "kind": "refill", "baseline": e.value.get("baseline"),
                            "text": "Refilled (back to OK)"})
        else:
            entries.append({"ts": e.ts, "kind": "state_" + state.lower(), "baseline": e.value.get("baseline"),
                            "text": f"State {state}"})
        prev_state = state

    rows = db.scalars(select(ListItem).where(ListItem.strap_id == strap.device_id)).all()
    for row in rows:
        entries.append({"ts": row.added_at, "kind": "listed", "text": f"{row.item.name} added to shopping list"})
        if row.order is not None:
            entries.append({"ts": row.order.created_at, "kind": "ordered",
                            "text": f"In order #{row.order.id} ({row.order.status.value})"})
            if row.order.sent_to_shop_at:
                entries.append({"ts": row.order.sent_to_shop_at, "kind": "sent_to_shop",
                                "text": f"Order #{row.order.id} sent to shop"})
    entries.sort(key=lambda x: x["ts"], reverse=True)
    return {"device_id": strap.device_id, "display_name": strap.display_name, "entries": entries}


# --- settings ----------------------------------------------------------------

def settings_out(db: Session) -> dict:
    owner = rules.get_owner(db)
    shop = owner.shop
    s = get_settings()
    return {
        "owner": {"name": owner.name, "whatsapp_number": owner.whatsapp_number,
                  "list_threshold_inr": owner.list_threshold_inr},
        "shop": None if shop is None else {"name": shop.name, "whatsapp_number": shop.whatsapp_number,
                                           "opted_in": shop.opted_in},
        "global": settings_store.get_all(db),
        "messaging_mode": s.messaging_mode,
        "dev_hold_seconds": s.dev_hold_seconds,
    }


@router.get("/settings")
def get_app_settings(db: Session = Depends(get_db)):
    out = settings_out(db)
    db.commit()
    return out


@router.put("/settings")
def put_app_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    owner = rules.get_owner(db)
    if body.owner:
        for field, value in body.owner.model_dump(exclude_none=True).items():
            setattr(owner, field, value)
    if body.shop:
        values = body.shop.model_dump(exclude_none=True)
        if owner.shop is None:
            owner.shop = Shop(name=values.get("name", "My shop"), whatsapp_number=values.get("whatsapp_number", ""),
                              opted_in=values.get("opted_in", False))
            db.add(owner.shop)
        else:
            for field, value in values.items():
                setattr(owner.shop, field, value)
    if body.global_:
        settings_store.set_values(db, body.global_.model_dump(exclude_none=True))
    db.commit()
    return settings_out(db)


# --- catalog -----------------------------------------------------------------

@router.get("/items")
def list_items(db: Session = Depends(get_db)):
    return [item_out(i) for i in db.scalars(select(Item).order_by(Item.name)).all()]


@router.post("/items", status_code=201)
def create_item(body: ItemIn, db: Session = Depends(get_db)):
    item = Item(**body.model_dump())
    db.add(item)
    db.commit()
    return item_out(item)


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemIn, db: Session = Depends(get_db)):
    item = get_item_or_404(db, item_id)
    for field, value in body.model_dump().items():
        setattr(item, field, value)
    db.flush()
    rules.reprice_pending(db, item, clock.now())
    db.commit()
    return item_out(item)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = get_item_or_404(db, item_id)
    if db.query(ListItem).filter(ListItem.item_id == item_id).first() is not None:
        raise HTTPException(409, "item is used on a shopping list or order; edit it instead")
    db.query(Strap).filter(Strap.item_id == item_id).update({Strap.item_id: None})
    db.delete(item)
    db.commit()
    return {"ok": True}


# --- shopping list and orders ----------------------------------------------------

def row_out(row: ListItem) -> dict:
    return {
        "id": row.id,
        "strap_id": row.strap_id,
        "strap_name": row.strap.display_name if row.strap else None,
        "item_id": row.item_id,
        "item_name": row.item.name,
        "qty": row.qty,
        "price_at_time_inr": row.price_at_time_inr,
        "line_total_inr": row.line_total_inr,
        "needs_price": row.needs_price,
        "status": row.status.value,
        "added_at": row.added_at,
    }


def order_out(order: Order) -> dict:
    return {
        "id": order.id,
        "status": order.status.value,
        "unsent": order.status.value == "send_failed",
        "total_inr": order.total_inr,
        "shop": order.shop.name if order.shop else (order.owner.shop.name if order.owner.shop else None),
        "created_at": order.created_at,
        "owner_sent_at": order.owner_sent_at,
        "reminder_sent_at": order.reminder_sent_at,
        "sent_to_shop_at": order.sent_to_shop_at,
        "last_error": order.last_error,
        "items": [{"name": r.item.name, "qty": r.qty, "line_total_inr": r.line_total_inr, "status": r.status.value}
                  for r in order.rows],
    }


def _list_out(db: Session) -> dict:
    summary = rules.list_summary(db, rules.get_owner(db))
    return {**summary, "rows": [row_out(r) for r in summary["rows"]]}


@router.get("/list")
def get_list(db: Session = Depends(get_db)):
    out = _list_out(db)
    db.commit()
    return out


@router.post("/list/items", status_code=201)
def add_to_list(body: ListAdd, db: Session = Depends(get_db)):
    owner = rules.get_owner(db)
    now = clock.now()
    try:
        if body.strap_id:
            strap = owned_strap(db, body.strap_id)
            if strap.item is None:
                raise HTTPException(422, "give this strap a contents label first")
            rules.add_list_item(db, owner, strap.item, now, strap=strap)
        else:
            rules.add_list_item(db, owner, get_item_or_404(db, body.item_id), now)
        rules.check_threshold(db, owner, now)
    except rules.RuleError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return _list_out(db)


@router.delete("/list/items/{row_id}")
def remove_from_list(row_id: int, db: Session = Depends(get_db)):
    owner = rules.get_owner(db)
    row = db.get(ListItem, row_id)
    if row is None or row.owner_id != owner.id:
        raise HTTPException(404, "list row not found")
    if row.status != ListStatus.pending:
        raise HTTPException(409, "only pending rows can be removed")
    row.status = ListStatus.cancelled
    db.commit()
    return _list_out(db)


@router.post("/list/send")
def send_list_now(db: Session = Depends(get_db)):
    try:
        order = rules.send_now(db, rules.get_owner(db), clock.now())
    except rules.RuleError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return order_out(order)


@router.get("/orders")
def list_orders(limit: int = 20, db: Session = Depends(get_db)):
    owner = rules.get_owner(db)
    orders = db.scalars(select(Order).where(Order.owner_id == owner.id)
                        .order_by(Order.created_at.desc(), Order.id.desc()).limit(max(1, min(limit, 100)))).all()
    out = [order_out(o) for o in orders]
    db.commit()
    return out


def owned_order(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None or order.owner_id != rules.get_owner(db).id:
        raise HTTPException(404, "order not found")
    return order


@router.post("/orders/{order_id}/retry")
def retry_order(order_id: int, db: Session = Depends(get_db)):
    order = owned_order(db, order_id)
    try:
        rules.retry_order(db, order, clock.now())
    except rules.RuleError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return order_out(order)


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, db: Session = Depends(get_db)):
    order = owned_order(db, order_id)
    try:
        rules.cancel_order(db, order)
    except rules.RuleError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return order_out(order)
