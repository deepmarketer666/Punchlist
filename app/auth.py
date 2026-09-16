"""Session handling: JWT in an HttpOnly cookie (browser) or Authorization header (API clients)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from functools import wraps

import jwt
from flask import current_app, g, request

from .validation import HttpError

COOKIE_NAME = "pl_token"


def _config():
    return current_app.config["PUNCHLIST"]


def _store():
    return current_app.extensions["punchlist_store"]


def create_token(user: dict) -> str:
    cfg = _config()
    now = datetime.now(timezone.utc)
    payload = {"sub": user["id"], "iat": now, "exp": now + cfg.jwt_expires}
    return jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")


def set_session_cookie(response, token: str) -> None:
    cfg = _config()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(cfg.jwt_expires.total_seconds()),
        httponly=True,
        secure=cfg.is_prod,  # Render serves over HTTPS
        samesite="Lax",
        path="/",
    )


def clear_session(response) -> None:
    cfg = _config()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=cfg.is_prod, samesite="Lax")


def _token_from_request() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def require_auth(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _token_from_request()
        if not token:
            raise HttpError(401, "Sign in to continue")
        try:
            payload = jwt.decode(token, _config().jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HttpError(401, "Your session has expired. Sign in again.") from None

        try:
            user_id = str(uuid.UUID(str(payload.get("sub", ""))))
        except ValueError:
            raise HttpError(401, "Your session is invalid. Sign in again.") from None

        user = _store().find_user_by_id(user_id)
        if not user:
            raise HttpError(401, "Account not found. Sign in again.")
        g.user = user
        return view(*args, **kwargs)

    return wrapper
