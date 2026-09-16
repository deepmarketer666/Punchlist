"""WSGI entry point.

Production (Render):  gunicorn wsgi:app      (settings in gunicorn.conf.py)
Local development:    python wsgi.py
"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Flask's built-in server, for local development only.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True, use_reloader=True)
