"""Punchlist - Flask application factory."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, abort, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .db import create_store, init_with_retry, seed_demo_data
from .security import api_limiter, init_security
from .validation import HttpError

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
log = logging.getLogger("punchlist")

API_INDEX = [
    "GET    /api/health",
    "POST   /api/auth/register   { name, email, password }",
    "POST   /api/auth/login      { email, password }",
    "POST   /api/auth/logout",
    "GET    /api/auth/me",
    "GET    /api/tasks?status=&priority=&q=&sort=created|due|priority",
    "GET    /api/tasks/stats",
    "GET    /api/tasks/export.csv",
    "GET    /api/tasks/<id>",
    "POST   /api/tasks           { title, notes?, status?, priority?, dueDate? }",
    "PATCH  /api/tasks/<id>",
    "DELETE /api/tasks/<id>",
]


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def create_app(config: Config | None = None, store=None) -> Flask:
    _configure_logging()
    config = config or Config.from_env()

    app = Flask(__name__, static_folder=None)
    app.config["PUNCHLIST"] = config
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024  # 100 KB request bodies
    app.json.sort_keys = False

    # Render terminates TLS at its proxy: trust one hop so request.scheme / remote_addr are right.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    if store is None:
        store = create_store(config)
        init_with_retry(store)
        log.info("using %s storage", store.kind)
        if store.kind == "memory":
            log.warning("data is kept in memory and will be lost on restart. Set DATABASE_URL to persist.")
        if config.seed_demo:
            seed_demo_data(store, config.demo_user)
    app.extensions["punchlist_store"] = store

    init_security(app, config)
    _register_api(app)
    _register_errors(app)
    _register_frontend(app, config)
    return app


def _register_api(app: Flask) -> None:
    from .routes import auth, health, tasks

    @app.before_request
    def limit_api():
        if request.path.startswith("/api/"):
            api_limiter.check()

    app.register_blueprint(health.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(tasks.bp)

    @app.route("/api/<path:rest>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(rest):
        abort(404)

    @app.get("/api")
    def api_index():
        return jsonify({"name": "Punchlist API", "version": app.config["PUNCHLIST"].version,
                        "endpoints": API_INDEX})


def _error_response(status: int, message: str, fields=None):
    body = {"message": message, "requestId": g.get("request_id")}
    if fields:
        body["fields"] = fields
    return jsonify({"error": body}), status


def _register_errors(app: Flask) -> None:
    @app.errorhandler(HttpError)
    def handle_http_error(err: HttpError):
        response, status = _error_response(err.status, err.message, err.fields)
        if getattr(err, "retry_after", None):
            response.headers["Retry-After"] = str(err.retry_after)
        return response, status

    @app.errorhandler(HTTPException)
    def handle_werkzeug_error(err: HTTPException):
        if not request.path.startswith("/api"):
            return err  # default HTML page for non-API paths (e.g. missing static file)
        messages = {
            404: f"No API route for {request.method} {request.path}",
            405: f"{request.method} is not allowed on {request.path}",
            413: "Request body is too large",
        }
        return _error_response(err.code or 500, messages.get(err.code, err.description))

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        log.exception("unhandled error on %s %s (request %s)", request.method, request.path, g.get("request_id"))
        return _error_response(500, "Something went wrong on the server")


def _register_frontend(app: Flask, config: Config) -> None:
    cache_seconds = 3600 if config.is_prod else 0

    def index():
        response = send_from_directory(PUBLIC_DIR, "index.html", max_age=0)
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/")
    def root():
        return index()

    @app.get("/<path:path>")
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            abort(404)
        file_path = (PUBLIC_DIR / path).resolve()
        if file_path.is_file() and PUBLIC_DIR in file_path.parents:
            return send_from_directory(PUBLIC_DIR, path, max_age=cache_seconds)
        if "." in path.rsplit("/", 1)[-1]:
            abort(404)  # a missing asset, not an app route
        return index()  # single-page app fallback
