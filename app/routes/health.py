"""Health check used by Render to decide whether an instance can take traffic."""

import logging
import os
import time
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

bp = Blueprint("health", __name__)
log = logging.getLogger("punchlist.health")

_STARTED_MONO = time.monotonic()
_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@bp.get("/api/health")
def health():
    cfg = current_app.config["PUNCHLIST"]
    store = current_app.extensions["punchlist_store"]

    database = "ok"
    try:
        store.ping()
    except Exception as exc:  # noqa: BLE001
        database = "unreachable"
        log.error("database ping failed: %s", exc)

    commit = os.environ.get("RENDER_GIT_COMMIT")
    body = {
        "status": "ok" if database == "ok" else "degraded",
        "version": cfg.version,
        "environment": cfg.env,
        "storage": store.kind,
        "database": database,
        "uptimeSeconds": round(time.monotonic() - _STARTED_MONO),
        "startedAt": _STARTED_AT,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "commit": commit[:7] if commit else None,
        "region": os.environ.get("RENDER_REGION"),
        "pid": os.getpid(),
    }
    # 503 tells Render not to route traffic here while the database is down.
    return jsonify(body), 200 if database == "ok" else 503
