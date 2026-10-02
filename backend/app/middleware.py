"""Rate limiting, request size limits and security headers."""
import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import get_settings


class SlidingWindowLimiter:
    def __init__(self, clock=time.monotonic):
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._clock = clock

    def allow(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window_s:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True


class HardeningMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.limiter = SlidingWindowLimiter()

    def _limit_for(self, path: str) -> tuple[str, int] | None:
        settings = get_settings()
        if path.startswith("/api/device/"):
            return "device", settings.rate_limit_device_per_minute
        if path == "/api/login":
            return "login", settings.rate_limit_login_per_minute
        return None

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        path = request.url.path

        if request.method in ("POST", "PUT", "PATCH"):
            length = request.headers.get("content-length")
            if length is None and "chunked" in request.headers.get("transfer-encoding", ""):
                return JSONResponse({"detail": "Content-Length required"}, status_code=411)
            if length is not None and (not length.isdigit() or int(length) > settings.max_body_bytes):
                return JSONResponse({"detail": "request body too large"}, status_code=413)

        limit = self._limit_for(path)
        if limit is not None:
            bucket, per_minute = limit
            client = request.client.host if request.client else "unknown"
            if not self.limiter.allow(f"{bucket}:{client}", per_minute):
                return JSONResponse({"detail": "too many requests"}, status_code=429,
                                    headers={"Retry-After": "60"})

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
