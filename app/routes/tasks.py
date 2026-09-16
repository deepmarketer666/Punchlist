"""Task routes. Every route is scoped to the signed-in user."""

import csv
import io

from flask import Blueprint, Response, current_app, g, jsonify, request

from ..auth import require_auth
from ..validation import HttpError, assert_uuid, validate_task, validate_task_query
from . import json_body

bp = Blueprint("tasks", __name__, url_prefix="/api/tasks")

CSV_FIELDS = ["id", "title", "notes", "status", "priority", "dueDate", "createdAt", "updatedAt"]


def _store():
    return current_app.extensions["punchlist_store"]


def _csv_cell(value) -> str:
    text = "" if value is None else str(value)
    # Neutralise spreadsheet formula injection.
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") else text


@bp.get("")
@require_auth
def list_tasks():
    filters = validate_task_query(request.args)
    tasks = _store().list_tasks(g.user["id"], **filters)
    return jsonify({"tasks": tasks, "count": len(tasks)})


@bp.get("/stats")
@require_auth
def stats():
    data = _store().get_stats(g.user["id"])
    data["completionRate"] = round(data["done"] / data["total"] * 100) if data["total"] else 0
    return jsonify({"stats": data})


@bp.get("/export.csv")
@require_auth
def export_csv():
    tasks = _store().list_tasks(g.user["id"], sort="created")
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(CSV_FIELDS)
    for task in tasks:
        writer.writerow([_csv_cell(task[f]) for f in CSV_FIELDS])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="punchlist-tasks.csv"'},
    )


@bp.get("/<task_id>")
@require_auth
def get_task(task_id):
    assert_uuid(task_id)
    task = _store().get_task(g.user["id"], task_id)
    if not task:
        raise HttpError(404, "Task not found")
    return jsonify({"task": task})


@bp.post("")
@require_auth
def create_task():
    data = validate_task(json_body())
    task = _store().create_task(g.user["id"], data)
    response = jsonify({"task": task})
    response.status_code = 201
    response.headers["Location"] = f"/api/tasks/{task['id']}"
    return response


@bp.patch("/<task_id>")
@require_auth
def update_task(task_id):
    assert_uuid(task_id)
    patch = validate_task(json_body(), partial=True)
    task = _store().update_task(g.user["id"], task_id, patch)
    if not task:
        raise HttpError(404, "Task not found")
    return jsonify({"task": task})


@bp.delete("/<task_id>")
@require_auth
def delete_task(task_id):
    assert_uuid(task_id)
    if not _store().delete_task(g.user["id"], task_id):
        raise HttpError(404, "Task not found")
    return "", 204
