"""Account routes."""

from flask import Blueprint, current_app, g, jsonify, make_response
from werkzeug.security import check_password_hash, generate_password_hash

from ..auth import clear_session, create_token, require_auth, set_session_cookie
from ..db import DuplicateEmail
from ..security import auth_limiter
from ..validation import HttpError, validate_login, validate_registration
from . import json_body

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Checked when an email isn't found, so response time doesn't reveal which accounts exist.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def _store():
    return current_app.extensions["punchlist_store"]


def _session_response(user: dict, status: int):
    token = create_token(user)
    response = jsonify({"user": user, "token": token})
    response.status_code = status
    set_session_cookie(response, token)
    return response


@bp.post("/register")
@auth_limiter
def register():
    data = validate_registration(json_body())
    store = _store()

    if store.find_user_by_email(data["email"]):
        raise HttpError(409, "An account with this email already exists", {"email": "Already registered"})
    try:
        user = store.create_user(data["name"], data["email"], generate_password_hash(data["password"]))
    except DuplicateEmail:
        raise HttpError(409, "An account with this email already exists", {"email": "Already registered"}) from None

    return _session_response(user, 201)


@bp.post("/login")
@auth_limiter
def login():
    data = validate_login(json_body())
    record = _store().find_user_by_email(data["email"])
    ok = check_password_hash(record["passwordHash"] if record else _DUMMY_HASH, data["password"])
    if not record or not ok:
        raise HttpError(401, "Email or password is incorrect")

    user = {k: v for k, v in record.items() if k != "passwordHash"}
    return _session_response(user, 200)


@bp.post("/logout")
def logout():
    response = make_response("", 204)
    clear_session(response)
    return response


@bp.get("/me")
@require_auth
def me():
    return jsonify({"user": g.user})
