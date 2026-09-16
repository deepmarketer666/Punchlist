"""In-memory store. Data lives only as long as the process - fine for local dev and quick tests.

Gunicorn is configured to run a single worker in this mode (see gunicorn.conf.py),
because each worker process would otherwise have its own separate copy of the data.
"""

from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone

from ..validation import PRIORITY_RANK, today_iso
from .base import DuplicateEmail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _public_user(user: dict | None) -> dict | None:
    if not user:
        return None
    return {k: user[k] for k in ("id", "name", "email", "createdAt")}


class MemoryStore:
    kind = "memory"

    def __init__(self) -> None:
        self._users: dict[str, dict] = {}
        self._tasks: dict[str, dict] = {}
        self._lock = threading.RLock()

    # lifecycle ------------------------------------------------------------
    def init(self) -> None:
        pass

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        pass

    # users ----------------------------------------------------------------
    def create_user(self, name: str, email: str, password_hash: str) -> dict:
        with self._lock:
            if any(u["email"] == email for u in self._users.values()):
                raise DuplicateEmail(email)
            user = {"id": str(uuid.uuid4()), "name": name, "email": email,
                    "passwordHash": password_hash, "createdAt": _now()}
            self._users[user["id"]] = user
            return _public_user(user)

    def find_user_by_email(self, email: str) -> dict | None:
        with self._lock:
            for user in self._users.values():
                if user["email"] == email:
                    return dict(user)
        return None

    def find_user_by_id(self, user_id: str) -> dict | None:
        with self._lock:
            return _public_user(self._users.get(user_id))

    # tasks ----------------------------------------------------------------
    def list_tasks(self, user_id: str, status=None, priority=None, q=None, sort=None) -> list[dict]:
        needle = q.lower() if q else None
        with self._lock:
            items = [
                copy.deepcopy(t) for t in self._tasks.values()
                if t["userId"] == user_id
                and (not status or t["status"] == status)
                and (not priority or t["priority"] == priority)
                and (not needle or needle in t["title"].lower() or needle in t["notes"].lower())
            ]

        # Newest first as the base order; Python's sort is stable, so later sorts keep it for ties.
        items.sort(key=lambda t: t["createdAt"], reverse=True)
        if sort == "due":
            items.sort(key=lambda t: t["dueDate"] or "9999-12-31")
        elif sort == "priority":
            items.sort(key=lambda t: PRIORITY_RANK[t["priority"]], reverse=True)
        return items

    def get_task(self, user_id: str, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return copy.deepcopy(task) if task and task["userId"] == user_id else None

    def create_task(self, user_id: str, data: dict) -> dict:
        ts = _now()
        task = {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "title": data["title"],
            "notes": data.get("notes", ""),
            "status": data.get("status", "todo"),
            "priority": data.get("priority", "medium"),
            "dueDate": data.get("dueDate"),
            "createdAt": ts,
            "updatedAt": ts,
        }
        with self._lock:
            self._tasks[task["id"]] = task
            return copy.deepcopy(task)

    def update_task(self, user_id: str, task_id: str, patch: dict) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task["userId"] != user_id:
                return None
            task.update(patch)
            task["updatedAt"] = _now()
            return copy.deepcopy(task)

    def delete_task(self, user_id: str, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task["userId"] != user_id:
                return False
            del self._tasks[task_id]
            return True

    def get_stats(self, user_id: str) -> dict:
        today = today_iso()
        stats = {"total": 0, "todo": 0, "in_progress": 0, "done": 0, "overdue": 0, "highOpen": 0}
        with self._lock:
            for t in self._tasks.values():
                if t["userId"] != user_id:
                    continue
                stats["total"] += 1
                stats[t["status"]] += 1
                if t["status"] != "done" and t["dueDate"] and t["dueDate"] < today:
                    stats["overdue"] += 1
                if t["status"] != "done" and t["priority"] == "high":
                    stats["highOpen"] += 1
        return stats
