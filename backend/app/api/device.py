from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..ingest import PayloadError, ingest_event, pop_commands
from ..models import Strap, StrapState
from ..schemas import CommandsResponse, DeviceEvent, DeviceEventResponse, RegisterRequest, RegisterResponse
from ..security import constant_eq, current_device, hash_token, new_claim_code, new_device_token

router = APIRouter(prefix="/api/device", tags=["device"])


@router.post("/register", response_model=RegisterResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if not constant_eq(body.provision_secret, get_settings().device_provision_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad provisioning secret")
    token = new_device_token()
    strap = db.get(Strap, body.device_id)
    if strap is None:
        strap = Strap(device_id=body.device_id, state=StrapState.UNKNOWN, claim_code=new_claim_code(db),
                      device_token_hash=hash_token(token))
        db.add(strap)
    else:
        # Re-registration (e.g. after a factory reset) rotates the token but keeps name, label and owner.
        strap.device_token_hash = hash_token(token)
        if strap.owner_id is None and strap.claim_code is None:
            strap.claim_code = new_claim_code(db)
    db.commit()
    return RegisterResponse(device_token=token, claim_code=strap.claim_code)


@router.post("/events", response_model=DeviceEventResponse)
def post_event(body: DeviceEvent, strap: Strap = Depends(current_device), db: Session = Depends(get_db)):
    try:
        result = ingest_event(db, strap, body.type, body.payload)
    except PayloadError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    commands = pop_commands(strap)
    db.commit()
    return DeviceEventResponse(stored=result.stored, commands=commands)


@router.get("/commands", response_model=CommandsResponse)
def get_commands(strap: Strap = Depends(current_device), db: Session = Depends(get_db)):
    commands = pop_commands(strap)
    db.commit()
    return CommandsResponse(commands=commands)
