import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Strap

# A-Z and 2-9 without look-alikes (I, O, 0, 1).
CLAIM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def new_device_token() -> str:
    return secrets.token_hex(32)


def hash_token(token: str) -> str:
    # Tokens are 256-bit random values, so a plain SHA-256 is sufficient (no need for a slow KDF).
    return hashlib.sha256(token.encode()).hexdigest()


def new_claim_code(db: Session) -> str:
    while True:
        code = "".join(secrets.choice(CLAIM_ALPHABET) for _ in range(6))
        if db.query(Strap).filter(Strap.claim_code == code).first() is None:
            return code


def current_device(
    authorization: str | None = Header(default=None),
    x_device_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Strap:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown device or bad token")
    if not authorization or not x_device_id or not authorization.startswith("Bearer "):
        raise unauthorized
    strap = db.get(Strap, x_device_id)
    if strap is None or not constant_eq(strap.device_token_hash, hash_token(authorization[7:].strip())):
        raise unauthorized
    return strap


# --- dashboard session ---------------------------------------------------

SESSION_COOKIE = "sb_session"
SESSION_MAX_AGE = 7 * 24 * 3600


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="dashboard-session")


def make_session_token() -> str:
    return _serializer().dumps({"u": "owner"})


def session_valid(token: str | None) -> bool:
    if not token:
        return False
    try:
        _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return False
    return True


def require_dashboard(request: Request) -> None:
    if not session_valid(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
