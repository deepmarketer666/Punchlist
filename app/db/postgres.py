"""PostgreSQL store (psycopg 3). Used whenever DATABASE_URL is set."""

from __future__ import annotations

import logging
import os
import threading

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..validation import today_iso
from .base import DuplicateEmail

log = logging.getLogger("punchlist.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tasks (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'todo'   CHECK (status IN ('todo','in_progress','done')),
    priority   TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high')),
    due_date   DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS tasks_user_id_idx ON tasks (user_id);
"""

# Any constant works; it just serialises schema creation if several processes boot at once.
_SCHEMA_LOCK_KEY = 72_110_415

TASK_COLUMNS = """
    id::text AS id, user_id::text AS "userId", title, notes, status, priority,
    due_date AS "dueDate", created_at AS "createdAt", updated_at AS "updatedAt"
"""

# API field -> column. Also acts as the whitelist for PATCH.
UPDATABLE = {"title": "title", "notes": "notes", "status": "status",
             "priority": "priority", "dueDate": "due_date"}

ORDER_BY = {
    "created": "created_at DESC",
    "due": "due_date ASC NULLS LAST, created_at DESC",
    "priority": "CASE priority WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC, created_at DESC",
}


def _iso_ts(value) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _task(row: dict | None) -> dict | None:
    if not row:
        return None
    row["dueDate"] = row["dueDate"].isoformat() if row["dueDate"] else None
    row["createdAt"] = _iso_ts(row["createdAt"])
    row["updatedAt"] = _iso_ts(row["updatedAt"])
    return row


def _user(row: dict | None) -> dict | None:
    if row and "createdAt" in row:
        row["createdAt"] = _iso_ts(row["createdAt"])
    return row


class PostgresStore:
    kind = "postgres"

    def __init__(self, dsn: str, ssl: bool = False) -> None:
        self._dsn = dsn
        self._conn_kwargs = {"row_factory": dict_row}
        if ssl:
            self._conn_kwargs["sslmode"] = "require"
        self._pool: ConnectionPool | None = None
        self._pool_pid: int | None = None
        self._pool_lock = threading.Lock()

    # Connections must not be shared across forked Gunicorn workers, so each
    # process lazily opens its own pool the first time it needs the database.
    def _get_pool(self) -> ConnectionPool:
        pid = os.getpid()
        if self._pool is None or self._pool_pid != pid:
            with self._pool_lock:
                if self._pool is None or self._pool_pid != pid:
                    self._pool = ConnectionPool(
                        self._dsn,
                        min_size=1,
                        max_size=5,
                        kwargs=self._conn_kwargs,
                        check=ConnectionPool.check_connection,  # drop dead connections (e.g. after idle)
                        timeout=10,
                        open=True,
                    )
                    self._pool_pid = pid
        return self._pool

    def _fetchone(self, query, params=()):
        with self._get_pool().connection() as conn:
            return conn.execute(query, params).fetchone()

    def _fetchall(self, query, params=()):
        with self._get_pool().connection() as conn:
            return conn.execute(query, params).fetchall()

    # lifecycle ------------------------------------------------------------
    def init(self) -> None:
        # One-off connection (not the pool) so nothing is inherited by forked workers.
        with psycopg.connect(self._dsn, connect_timeout=10, **self._conn_kwargs) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
            conn.execute(SCHEMA)

    def ping(self) -> bool:
        self._fetchone("SELECT 1")
        return True

    def close(self) -> None:
        if self._pool is not None and self._pool_pid == os.getpid():
            self._pool.close()
            self._pool = None

    # users ----------------------------------------------------------------
    def create_user(self, name: str, email: str, password_hash: str) -> dict:
        try:
            return _user(self._fetchone(
                """INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)
                   RETURNING id::text AS id, name, email, created_at AS "createdAt" """,
                (name, email, password_hash),
            ))
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateEmail(email) from exc

    def find_user_by_email(self, email: str) -> dict | None:
        return _user(self._fetchone(
            """SELECT id::text AS id, name, email, password_hash AS "passwordHash",
                      created_at AS "createdAt"
               FROM users WHERE email = %s""",
            (email,),
        ))

    def find_user_by_id(self, user_id: str) -> dict | None:
        return _user(self._fetchone(
            'SELECT id::text AS id, name, email, created_at AS "createdAt" FROM users WHERE id = %s',
            (user_id,),
        ))

    # tasks ----------------------------------------------------------------
    def list_tasks(self, user_id: str, status=None, priority=None, q=None, sort=None) -> list[dict]:
        where = ["user_id = %s"]
        params: list = [user_id]
        if status:
            where.append("status = %s")
            params.append(status)
        if priority:
            where.append("priority = %s")
            params.append(priority)
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("(title ILIKE %s OR notes ILIKE %s)")
            params += [f"%{escaped}%", f"%{escaped}%"]

        query = (f"SELECT {TASK_COLUMNS} FROM tasks WHERE {' AND '.join(where)} "
                 f"ORDER BY {ORDER_BY.get(sort or 'created', ORDER_BY['created'])}")
        return [_task(r) for r in self._fetchall(query, params)]

    def get_task(self, user_id: str, task_id: str) -> dict | None:
        return _task(self._fetchone(
            f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = %s AND user_id = %s",
            (task_id, user_id),
        ))

    def create_task(self, user_id: str, data: dict) -> dict:
        return _task(self._fetchone(
            f"""INSERT INTO tasks (user_id, title, notes, status, priority, due_date)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING {TASK_COLUMNS}""",
            (user_id, data["title"], data.get("notes", ""), data.get("status", "todo"),
             data.get("priority", "medium"), data.get("dueDate")),
        ))

    def update_task(self, user_id: str, task_id: str, patch: dict) -> dict | None:
        fields = [(UPDATABLE[k], v) for k, v in patch.items() if k in UPDATABLE]
        if not fields:
            return self.get_task(user_id, task_id)

        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col, _ in fields
        )
        query = sql.SQL(
            "UPDATE tasks SET {}, updated_at = now() WHERE id = %s AND user_id = %s RETURNING "
        ).format(assignments) + sql.SQL(TASK_COLUMNS)
        return _task(self._fetchone(query, [v for _, v in fields] + [task_id, user_id]))

    def delete_task(self, user_id: str, task_id: str) -> bool:
        with self._get_pool().connection() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = %s AND user_id = %s", (task_id, user_id))
            return cur.rowcount > 0

    def get_stats(self, user_id: str) -> dict:
        return self._fetchone(
            """SELECT
                 COUNT(*)::int                                                         AS total,
                 COUNT(*) FILTER (WHERE status = 'todo')::int                          AS todo,
                 COUNT(*) FILTER (WHERE status = 'in_progress')::int                   AS in_progress,
                 COUNT(*) FILTER (WHERE status = 'done')::int                          AS done,
                 COUNT(*) FILTER (WHERE status <> 'done' AND due_date < %s::date)::int AS overdue,
                 COUNT(*) FILTER (WHERE status <> 'done' AND priority = 'high')::int   AS "highOpen"
               FROM tasks WHERE user_id = %s""",
            (today_iso(), user_id),
        )
