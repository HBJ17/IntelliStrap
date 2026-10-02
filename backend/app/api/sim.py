"""Simulator / dev endpoints: a WhatsApp inbox on screen and fake strap events."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import clock, rules
from ..config import get_settings
from ..db import get_db
from ..ingest import PayloadError, ingest_event
from ..messaging import ParsedReply, get_messenger
from ..models import Strap
from ..schemas import SimEvent, SimReply
from ..security import require_dashboard

router = APIRouter(prefix="/api/sim", tags=["simulator"], dependencies=[Depends(require_dashboard)])


def require_simulator() -> None:
    if get_settings().messaging_mode != "simulator":
        raise HTTPException(404, "simulator is only available when MESSAGING_MODE=simulator")


def require_dev() -> None:
    if not get_settings().is_dev:
        raise HTTPException(404, "dev-only endpoint")


@router.get("/messages", dependencies=[Depends(require_simulator)])
def messages():
    return {"messages": list(reversed(get_messenger().messages))}


@router.delete("/messages", dependencies=[Depends(require_simulator)])
def clear_messages():
    get_messenger().clear()
    return {"ok": True}


@router.post("/reply", dependencies=[Depends(require_simulator)])
def reply(body: SimReply, db: Session = Depends(get_db)):
    """Simulate the owner tapping Order / Not now on the owner-list message."""
    outcome = rules.handle_reply(db, ParsedReply(body.action, body.order_id), clock.now())
    db.commit()
    return {"outcome": outcome}


@router.post("/event", dependencies=[Depends(require_dev)])
def inject_event(body: SimEvent, db: Session = Depends(get_db)):
    strap = db.get(Strap, body.device_id)
    if strap is None:
        raise HTTPException(404, "unknown strap")
    try:
        result = ingest_event(db, strap, body.type, body.payload)
    except PayloadError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return {"ok": True, "stored": result.stored}


@router.post("/fast-forward", dependencies=[Depends(require_dev)])
def fast_forward(db: Session = Depends(get_db)):
    """Treat the LOW hold time as already elapsed and run the list rules now."""
    added = rules.evaluate_holds(db, clock.now(), hold=timedelta(0))
    db.commit()
    return {"added": len(added)}
