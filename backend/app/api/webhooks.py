import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import clock, rules
from ..db import get_db
from ..messaging import get_messenger
from ..security import twilio_signature_valid

router = APIRouter(tags=["webhooks"])
log = logging.getLogger(__name__)

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


@router.post("/webhooks/twilio")
async def twilio_webhook(request: Request, db: Session = Depends(get_db)):
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    # Signature first: nothing is parsed or acted on for an unsigned request.
    if not twilio_signature_valid(request, form):
        raise HTTPException(403, "invalid Twilio signature")

    reply = get_messenger().parse_webhook(form)
    if reply is not None:
        outcome = rules.handle_reply(db, reply, clock.now())
        db.commit()
        log.info("owner reply %s for order %s -> %s", reply.action, reply.order_id, outcome)
    return Response(EMPTY_TWIML, media_type="application/xml")
