# Punchlist (Python)

A small, production-shaped task tracker built to test deployments on [Render](https://render.com).
Python 3.12 with Flask and Gunicorn, PostgreSQL (or in-memory) storage, and a no-build HTML/CSS/JS frontend.
**Only Python is needed** - there is no Node.js or build step.

## Features

- **Accounts**: register, sign in, sign out. Passwords are hashed with scrypt (Werkzeug). Sessions are JWTs in an `HttpOnly` cookie; API clients can send `Authorization: Bearer <token>` instead.
- **Tasks**: create, edit, delete, and mark done. Each task has a title, notes, status (to do / in progress / done), priority, and optional due date.
- **Search, filter, sort**: search titles and notes, filter by status and priority, sort by newest, due date, or priority.
- **Progress summary**: done/total, overdue count, open high-priority count.
- **CSV export** of all your tasks.
- **Demo account** created on startup: `demo@punchlist.test` / `demo1234`.
- **Light and dark themes**, responsive down to mobile, keyboard accessible.
- **Ops**: `/api/health` (checks the database), Gunicorn with graceful shutdown, request IDs, security headers with a Content Security Policy, rate limiting, input validation, per-user data isolation, database retry on startup.
- **Tests**: 12 pytest API tests that run against in-memory storage or a real Postgres database.

## Project structure

```
punchlist/
├── render.yaml              # Render Blueprint (web service + Postgres)
├── .python-version          # Pins Python 3.12 on Render
├── requirements.txt         # Runtime dependencies
├── requirements-dev.txt     # + pytest
├── gunicorn.conf.py         # Production server settings (read automatically by Gunicorn)
├── wsgi.py                  # Entry point: `gunicorn wsgi:app` or `python wsgi.py`
├── app/
│   ├── __init__.py          # App factory: routes, errors, frontend serving
│   ├── config.py            # Environment configuration
│   ├── auth.py              # JWT sessions
│   ├── security.py          # Headers, request IDs, rate limiting
│   ├── validation.py        # Input validation
│   ├── db/
│   │   ├── __init__.py      # Picks Postgres or memory; seeds demo data
│   │   ├── postgres.py      # psycopg 3 + connection pool; schema created on boot
│   │   └── memory.py
│   └── routes/              # health, auth, tasks
├── public/                  # Frontend (index.html, css, js) served by Flask
└── tests/test_api.py
```

## Run locally

Requires Python 3.10 or newer (3.12 recommended).

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python wsgi.py            # http://127.0.0.1:5000
pytest                    # runs the test suite
```

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python wsgi.py
pytest
```

`python wsgi.py` uses Flask's development server with auto-reload. Gunicorn (used on Render) doesn't run on Windows, but you don't need it locally.

With no `DATABASE_URL`, the app keeps data in memory and it resets when the server restarts. To use a local Postgres database:

```bash
export DATABASE_URL=postgresql://user:password@localhost:5432/punchlist   # PowerShell: $env:DATABASE_URL="..."
python wsgi.py
```

Tables are created automatically on first start. To run the tests against Postgres, set `TEST_DATABASE_URL` instead and run `pytest`.

## Deploy to Render

First push this folder to a GitHub, GitLab, or Bitbucket repository.

```bash
git init
git add .
git commit -m "Punchlist initial commit"
git branch -M main
git remote add origin https://github.com/<you>/punchlist.git
git push -u origin main
```

### Option A: Blueprint (recommended - creates the app and database together)

1. In the Render Dashboard, choose **New > Blueprint**.
2. Connect the repository. Render reads `render.yaml` and shows a web service `punchlist` and a database `punchlist-db`.
3. Click **Apply**. Render creates the database, generates `JWT_SECRET`, sets `DATABASE_URL`, runs `pip install -r requirements.txt`, and starts `gunicorn wsgi:app`.
4. When the deploy is live, open `https://<your-service>.onrender.com/api/health`. It should report `"storage": "postgres"` and `"database": "ok"`.
5. Open the site and choose **Sign in with the demo account**.

> Render allows **one free Postgres database per workspace**. If you already have one, delete it, change the database `plan` in `render.yaml` to a paid plan, or use Option B.

### Option B: Web service only (no database)

1. Choose **New > Web Service** and connect the repository.
2. Settings:
   - Language / Runtime: **Python 3**
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn wsgi:app`
   - Instance type: **Free**
   - Health check path (under Advanced): `/api/health`
3. Environment variables:
   - `APP_ENV` = `production`
   - `JWT_SECRET` = a long random string (`python -c "import secrets; print(secrets.token_hex(32))"`)
4. Deploy. The app runs with in-memory storage and a single Gunicorn worker, and the sign-in page tells users data resets on restart. To add persistence later, create a Render Postgres database and set `DATABASE_URL` to its **Internal Database URL**.

### Render free tier behaviour to expect while testing

- Free web services spin down after 15 minutes without traffic; the next request takes about a minute while it starts.
- In-memory data is lost whenever the service restarts, redeploys, or spins down. Postgres data is kept.
- Free Postgres databases expire 30 days after creation, with a 14-day grace period to upgrade before deletion.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `APP_ENV` | No | `development` | Use `production` on Render (secure cookies, HSTS, HTTPS upgrades, static caching) |
| `JWT_SECRET` | In production | random in dev | Signs session tokens. The app refuses to start in production without it |
| `JWT_EXPIRES_IN` | No | `7d` | Session lifetime (`30m`, `12h`, `7d`) |
| `DATABASE_URL` | No | empty | Postgres connection string. Empty means in-memory storage |
| `DATABASE_SSL` | No | `false` | Set `true` for external Postgres URLs. Render external URLs (`*.render.com`) use SSL automatically |
| `SEED_DEMO` | No | `true` | Set `false` to skip the demo account |
| `WEB_CONCURRENCY` | No | `2` | Gunicorn workers when a database is set. Always 1 with in-memory storage |
| `GUNICORN_THREADS` | No | `4` | Threads per worker |
| `PORT` | No | `10000` (Gunicorn), `5000` (dev) | Render sets this automatically |
| `LOG_LEVEL` | No | `INFO` | Python and Gunicorn log level |

## API reference

All responses are JSON. Errors look like `{ "error": { "message": "...", "fields": { ... }, "requestId": "..." } }`.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api` | No | Lists endpoints |
| GET | `/api/health` | No | Service and database health (503 if the database is down) |
| POST | `/api/auth/register` | No | `{ name, email, password }` → `201 { user, token }` |
| POST | `/api/auth/login` | No | `{ email, password }` → `{ user, token }` |
| POST | `/api/auth/logout` | No | Clears the session cookie → `204` |
| GET | `/api/auth/me` | Yes | Current user |
| GET | `/api/tasks` | Yes | Query: `status`, `priority`, `q`, `sort` (`created`, `due`, `priority`) |
| GET | `/api/tasks/stats` | Yes | Counts by status, overdue, open high priority, completion rate |
| GET | `/api/tasks/export.csv` | Yes | CSV download |
| GET | `/api/tasks/<id>` | Yes | One task |
| POST | `/api/tasks` | Yes | `{ title, notes?, status?, priority?, dueDate? }` → `201` |
| PATCH | `/api/tasks/<id>` | Yes | Any subset of task fields. `dueDate: null` clears it |
| DELETE | `/api/tasks/<id>` | Yes | `204` |

### Try the API with Python

Uses only the standard library, so there's nothing extra to install.

```python
import json
import urllib.request

BASE = "https://<your-service>.onrender.com"

def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read() or "null")

token = call("POST", "/api/auth/login", {"email": "demo@punchlist.test", "password": "demo1234"})["token"]
print(call("GET", "/api/tasks", token=token)["count"], "tasks")
print(call("POST", "/api/tasks", {"title": "Created from Python", "priority": "high"}, token=token))
```

## Manual test checklist

1. `/api/health` returns `200` with `"status": "ok"`.
2. Sign in with the demo account; five sample tasks appear, one overdue.
3. Punch a task off with its circle button; the summary strip gains a punched hole.
4. Try to add a task with an empty title; the Title field shows an error.
5. Search for "notes", then filter by High priority; clear the filters.
6. Edit a task, change its due date, save, then delete it.
7. Export CSV and open the file.
8. Create a second account in a private window and confirm it can't see the demo tasks.
9. Toggle the theme, reload, and confirm the choice is remembered.
10. With Postgres: run **Manual Deploy** in Render and confirm your tasks are still there.

## Troubleshooting

- **Deploy log shows `JWT_SECRET must be set in production`**: add `JWT_SECRET` (Option B) or re-sync the Blueprint.
- **Health check returns 503**: the database is unreachable. Check that `DATABASE_URL` is the Internal Database URL and that the database and web service are in the same region.
- **Wrong Python version in the build log**: make sure `.python-version` is committed. A `PYTHON_VERSION` environment variable, if set, takes priority over it.
- **`python wsgi.py` fails with `ModuleNotFoundError`**: activate the virtual environment first, then run `pip install -r requirements-dev.txt`.
- **First request is slow**: the free instance was asleep; wait about a minute.
