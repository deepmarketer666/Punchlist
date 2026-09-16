"""Picks a storage backend and seeds demo data."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

from .base import DuplicateEmail
from .memory import MemoryStore
from .postgres import PostgresStore

log = logging.getLogger("punchlist.db")

__all__ = ["create_store", "init_with_retry", "seed_demo_data", "DuplicateEmail"]


def create_store(config):
    if config.database_url:
        # Render's external URLs (…render.com) need SSL; internal URLs don't.
        ssl = config.database_ssl or ".render.com" in config.database_url
        return PostgresStore(config.database_url, ssl=ssl)
    return MemoryStore()


def init_with_retry(store, attempts: int = 5) -> None:
    """The database can take a moment to accept connections right after it's created."""
    for attempt in range(1, attempts + 1):
        try:
            store.init()
            return
        except Exception as exc:  # noqa: BLE001 - retry on any connection problem
            if attempt == attempts:
                raise
            wait = attempt * 2
            log.warning("database init failed (%s); retrying in %ss (%s/%s)", exc, wait, attempt, attempts)
            time.sleep(wait)


def _days_from_today(days: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def seed_demo_data(store, demo) -> None:
    """Creates a demo account with sample tasks so testers can sign in straight away."""
    if store.find_user_by_email(demo.email):
        return
    try:
        user = store.create_user(demo.name, demo.email, generate_password_hash(demo.password))
    except DuplicateEmail:
        return  # another process seeded it first

    samples = [
        {"title": "Check the health endpoint after deploy",
         "notes": "GET /api/health should return status ok.", "status": "done", "priority": "high"},
        {"title": "Register a second account and confirm data is separate",
         "status": "in_progress", "priority": "high", "dueDate": _days_from_today(1)},
        {"title": "Try filtering by priority and searching notes",
         "notes": "Search looks at titles and notes.", "priority": "medium", "dueDate": _days_from_today(3)},
        {"title": "Edit a task and change its due date", "priority": "low", "dueDate": _days_from_today(7)},
        {"title": "Find the overdue task", "notes": "This one was due two days ago.",
         "priority": "medium", "dueDate": _days_from_today(-2)},
    ]
    for task in samples:
        store.create_task(user["id"], task)
    log.info("demo account ready: %s / %s", demo.email, demo.password)
