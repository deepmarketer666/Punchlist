"""Request IDs, security headers, and a small in-process rate limiter."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from functools import wraps

from flask import current_app, g, request

from .validation import HttpError


def _csp(is_prod: bool) -> str:
    directives = [
        "default-src 'self'",
        "base-uri 'self'",
        "script-src 'self'",
        "script-src-attr 'none'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        "object-src 'none'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ]
    if is_prod:
        # Only in production: it breaks plain-HTTP local dev in some browsers.
        directives.append("upgrade-insecure-requests")
    return "; ".join(directives)


def init_security(app, config) -> None:
    csp = _csp(config.is_prod)

    @app.before_request
    def assign_request_id():
        g.request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())

    @app.after_request
    def add_headers(response):
        response.headers["X-Request-Id"] = g.get("request_id", "")
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if config.is_prod:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


class RateLimiter:
    """Sliding-window limiter keyed by client IP.

    Counts are kept per process, which is fine for a small app. For multiple
    instances you'd move this to Redis (Render Key Value).
    """

    def __init__(self, limit: int, window_seconds: int, message: str):
        self.limit = limit
        self.window = window_seconds
        self.message = message
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= now - self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = int(bucket[0] + self.window - now) + 1
                return False, retry_after
            bucket.append(now)
            # Keep memory bounded if lots of distinct IPs show up.
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self.window}
            return True, 0

    def check(self) -> None:
        """Raises a 429 HttpError if the current client is over the limit."""
        if current_app.config["PUNCHLIST"].is_test:
            return
        allowed, retry_after = self.hit(request.remote_addr or "unknown")
        if not allowed:
            error = HttpError(429, self.message)
            error.retry_after = retry_after
            raise error

    def __call__(self, view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            self.check()
            return view(*args, **kwargs)

        return wrapper


auth_limiter = RateLimiter(20, 15 * 60, "Too many attempts. Wait 15 minutes and try again.")
api_limiter = RateLimiter(300, 60, "Too many requests. Slow down and try again shortly.")
