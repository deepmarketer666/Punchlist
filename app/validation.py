"""Input validation. Mirrors the rules the frontend expects."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

STATUSES = ("todo", "in_progress", "done")
PRIORITIES = ("low", "medium", "high")
SORTS = ("created", "due", "priority")
PRIORITY_RANK = {"low": 1, "medium": 2, "high": 3}

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class HttpError(Exception):
    def __init__(self, status: int, message: str, fields: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.fields = fields


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _str(body: dict, key: str) -> str:
    value = body.get(key)
    return value.strip() if isinstance(value, str) else ""


def _is_valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _raise_if(errors: dict[str, str]) -> None:
    if errors:
        raise HttpError(400, "Check the highlighted fields", errors)


def validate_registration(body: dict) -> dict:
    name = _str(body, "name")
    email = _str(body, "email").lower()
    password = body.get("password") if isinstance(body.get("password"), str) else ""

    errors = {}
    if not 2 <= len(name) <= 60:
        errors["name"] = "Name must be 2–60 characters"
    if not _EMAIL_RE.match(email) or len(email) > 254:
        errors["email"] = "Enter a valid email address"
    if not 8 <= len(password) <= 128:
        errors["password"] = "Password must be 8–128 characters"
    _raise_if(errors)
    return {"name": name, "email": email, "password": password}


def validate_login(body: dict) -> dict:
    email = _str(body, "email").lower()
    password = body.get("password") if isinstance(body.get("password"), str) else ""
    if not email or not password:
        raise HttpError(400, "Enter your email and password")
    return {"email": email, "password": password}


def validate_task(body: dict, partial: bool = False) -> dict:
    """Validates a task payload. With partial=True (PATCH) only provided fields are checked."""
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}

    if not partial or "title" in body:
        title = _str(body, "title")
        if not title or len(title) > 200:
            errors["title"] = "Title is required (max 200 characters)"
        else:
            out["title"] = title

    if "notes" in body:
        notes = body["notes"]
        if not isinstance(notes, str) or len(notes) > 2000:
            errors["notes"] = "Notes must be text up to 2000 characters"
        else:
            out["notes"] = notes.strip()

    if "status" in body:
        if body["status"] not in STATUSES:
            errors["status"] = f"Status must be one of: {', '.join(STATUSES)}"
        else:
            out["status"] = body["status"]

    if "priority" in body:
        if body["priority"] not in PRIORITIES:
            errors["priority"] = f"Priority must be one of: {', '.join(PRIORITIES)}"
        else:
            out["priority"] = body["priority"]

    if "dueDate" in body:
        due = body["dueDate"]
        if due is None or due == "":
            out["dueDate"] = None
        elif not _is_valid_date(due):
            errors["dueDate"] = "Due date must be YYYY-MM-DD"
        else:
            out["dueDate"] = due

    _raise_if(errors)
    if partial and not out:
        raise HttpError(400, "Nothing to update")
    return out


def validate_task_query(args) -> dict:
    def pick(key: str) -> str | None:
        value = (args.get(key) or "").strip()
        return value or None

    out = {"status": pick("status"), "priority": pick("priority"), "q": pick("q"), "sort": pick("sort")}
    errors = {}
    if out["status"] and out["status"] not in STATUSES:
        errors["status"] = "Unknown status filter"
    if out["priority"] and out["priority"] not in PRIORITIES:
        errors["priority"] = "Unknown priority filter"
    if out["sort"] and out["sort"] not in SORTS:
        errors["sort"] = f"Sort must be one of: {', '.join(SORTS)}"
    if out["q"] and len(out["q"]) > 100:
        errors["q"] = "Search is limited to 100 characters"
    _raise_if(errors)
    return out


def assert_uuid(value: str) -> None:
    if not _UUID_RE.match(value or ""):
        raise HttpError(404, "Task not found")
