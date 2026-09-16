"""Gunicorn settings for Render. Gunicorn loads this file automatically.

Start command:  gunicorn wsgi:app
"""

import os

# Render routes traffic to the port in $PORT (10000 by default) on 0.0.0.0.
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"

# With in-memory storage every worker would hold its own separate data,
# so use exactly one worker unless a real database is configured.
_has_database = bool(os.environ.get("DATABASE_URL"))
workers = int(os.environ.get("WEB_CONCURRENCY", "2")) if _has_database else 1
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))

# Build the app (schema creation, demo seeding) once in the master process
# before forking workers. Database pools are opened lazily per worker.
preload_app = True

timeout = 30
graceful_timeout = 20   # Render sends SIGTERM on deploys; finish in-flight requests
keepalive = 5

# Render's proxy sets X-Forwarded-* headers; the app applies ProxyFix for one hop.
forwarded_allow_ips = "*"

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s "%(r)s" %(s)s %(b)sB %(M)sms'
