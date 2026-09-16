"""API integration tests.

    pytest                                              # in-memory storage
    TEST_DATABASE_URL=postgres://... pytest             # against a real Postgres database
"""

import os
import uuid

import pytest

from app import create_app
from app.config import Config
from app.db import create_store, seed_demo_data

DEMO = {"email": "demo@punchlist.test", "password": "demo1234"}
DB_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(scope="module")
def app():
    config = Config.from_env({
        "APP_ENV": "test",
        "JWT_SECRET": "test-secret",
        "DATABASE_URL": DB_URL,
        "SEED_DEMO": "true",
    })
    store = create_store(config)
    store.init()
    seed_demo_data(store, config.demo_user)
    application = create_app(config, store=store)
    yield application
    store.close()


@pytest.fixture
def client(app):
    return app.test_client()


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def register(client, email=None):
    email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
    res = client.post("/api/auth/register", json={"name": "Tester", "email": email, "password": "password123"})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["token"]


def test_health_reports_ok(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "ok"
    assert body["storage"] == ("postgres" if DB_URL else "memory")


def test_serves_frontend_and_spa_fallback(client):
    for path in ("/", "/some/deep/link"):
        res = client.get(path)
        assert res.status_code == 200
        assert b"<title>Punchlist</title>" in res.data
    assert client.get("/css/styles.css").status_code == 200
    assert client.get("/css/missing.css").status_code == 404


def test_security_headers(client):
    res = client.get("/")
    assert "script-src 'self'" in res.headers["Content-Security-Policy"]
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Request-Id"]


def test_unknown_api_routes_return_json_404(client):
    for method in ("get", "post", "delete"):
        res = getattr(client, method)("/api/nope")
        assert res.status_code == 404
        assert res.get_json()["error"]["message"]


def test_registration_validates_and_rejects_duplicates(client):
    bad = client.post("/api/auth/register", json={"name": "A", "email": "x", "password": "1"})
    assert bad.status_code == 400
    assert sorted(bad.get_json()["error"]["fields"]) == ["email", "name", "password"]

    email = f"dupe-{uuid.uuid4().hex[:8]}@example.com"
    register(client, email)
    dupe = client.post("/api/auth/register", json={"name": "Again", "email": email.upper(), "password": "password123"})
    assert dupe.status_code == 409


def test_login_with_demo_account_and_bad_password(client):
    ok = client.post("/api/auth/login", json=DEMO)
    assert ok.status_code == 200
    cookie = ok.headers["Set-Cookie"]
    assert "pl_token=" in cookie and "HttpOnly" in cookie

    me = client.get("/api/auth/me", headers=auth_header(ok.get_json()["token"]))
    assert me.get_json()["user"]["email"] == DEMO["email"]
    assert "passwordHash" not in me.get_json()["user"]

    # The cookie alone also authenticates (browser flow)
    assert client.get("/api/auth/me").status_code == 200

    bad = client.post("/api/auth/login", json={**DEMO, "password": "wrong"})
    assert bad.status_code == 401


def test_logout_clears_cookie(app):
    client = app.test_client()
    client.post("/api/auth/login", json=DEMO)
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_tasks_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/tasks", headers=auth_header("garbage")).status_code == 401


def test_task_crud_filters_stats_and_export(client):
    h = auth_header(register(client))

    created = client.post("/api/tasks", headers=h, json={"title": "Write tests", "priority": "high", "dueDate": "2000-01-01"})
    assert created.status_code == 201
    task_id = created.get_json()["task"]["id"]
    assert created.get_json()["task"]["status"] == "todo"
    assert created.headers["Location"] == f"/api/tasks/{task_id}"

    client.post("/api/tasks", headers=h, json={"title": "Ship it", "notes": "deploy to render"})

    invalid = client.post("/api/tasks", headers=h, json={"title": "", "dueDate": "2024-02-30"})
    assert invalid.status_code == 400
    assert {"title", "dueDate"} <= set(invalid.get_json()["error"]["fields"])

    assert client.get("/api/tasks?q=RENDER", headers=h).get_json()["count"] == 1
    high = client.get("/api/tasks?priority=high&sort=priority", headers=h).get_json()
    assert high["tasks"][0]["id"] == task_id
    assert client.get("/api/tasks?sort=bogus", headers=h).status_code == 400

    stats = client.get("/api/tasks/stats", headers=h).get_json()["stats"]
    assert stats["total"] == 2 and stats["overdue"] == 1

    patched = client.patch(f"/api/tasks/{task_id}", headers=h, json={"status": "done", "dueDate": None})
    assert patched.status_code == 200
    assert patched.get_json()["task"]["status"] == "done"
    assert patched.get_json()["task"]["dueDate"] is None
    assert client.patch(f"/api/tasks/{task_id}", headers=h, json={}).status_code == 400

    stats = client.get("/api/tasks/stats", headers=h).get_json()["stats"]
    assert stats["done"] == 1 and stats["completionRate"] == 50

    csv_res = client.get("/api/tasks/export.csv", headers=h)
    assert csv_res.status_code == 200
    assert csv_res.mimetype == "text/csv"
    assert len(csv_res.get_data(as_text=True).strip().split("\r\n")) == 3

    assert client.delete(f"/api/tasks/{task_id}", headers=h).status_code == 204
    assert client.get(f"/api/tasks/{task_id}", headers=h).status_code == 404
    assert client.get("/api/tasks/not-a-uuid", headers=h).status_code == 404


def test_search_treats_wildcards_literally(client):
    h = auth_header(register(client))
    client.post("/api/tasks", headers=h, json={"title": "100% done"})
    client.post("/api/tasks", headers=h, json={"title": "Something else"})
    assert client.get("/api/tasks?q=%25", headers=h).get_json()["count"] == 1


def test_users_cannot_see_each_others_tasks(client):
    alice = auth_header(register(client))
    bob = auth_header(register(client))
    task_id = client.post("/api/tasks", headers=alice, json={"title": "Private"}).get_json()["task"]["id"]

    assert client.get(f"/api/tasks/{task_id}", headers=bob).status_code == 404
    assert client.patch(f"/api/tasks/{task_id}", headers=bob, json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/tasks/{task_id}", headers=bob).status_code == 404
    assert client.get("/api/tasks", headers=bob).get_json()["count"] == 0


def test_malformed_json_returns_400(client):
    res = client.post("/api/auth/login", data="{bad json", content_type="application/json")
    assert res.status_code == 400
    assert res.get_json()["error"]["message"] == "Request body must be valid JSON"
