"""
app.py — DSA Tracker v4 entry point.

This used to be a single 2,400+ line file containing every route, every
helper, the DB schema, the User model, and the scheduler. It's now just
the assembly point:

  1. `extensions` creates the shared Flask `app` (config, login manager,
     CORS, before/after_request hooks).
  2. `database.db.init_db()` creates tables if they don't exist yet — this
     runs unconditionally at import time, same as the original app.py did
     (so it also runs correctly under gunicorn, not just `python app.py`).
  3. Each `routes.*` module is imported for its side effect of registering
     `@app.route(...)` handlers onto the shared `app` object. No Flask
     Blueprints are used, specifically so every endpoint name (and every
     `url_for(...)` call, in Python and in the Jinja templates) stays
     byte-for-byte identical to the original monolith.
  4. Error handlers and the dev-server bootstrap live here, same as they
     did at the bottom of the old app.py.
"""

import os
import sys

from extensions import app
from database.db import init_db
from services.tracker_service import ensure_tracker_schema

# ── DB (PostgreSQL only — see database/db.py) ────────────────────────────────
init_db()

# ── Route modules (import for side-effect route registration) ───────────────
from routes import auth            # noqa: E402,F401  /, /login, /signup, /logout, /admin/login, email verification
from routes import dashboard       # noqa: E402,F401  /dashboard, challenge/mentor completion
from routes import settings        # noqa: E402,F401  /settings, cookie endpoints, leetcode connect, feedback
from routes import sync            # noqa: E402,F401  /sync, /import_lc
from routes import tracker         # noqa: E402,F401  /problems, /export_csv, daily tracker
from routes import google_sheet    # noqa: E402,F401  /my_sheet
from routes import leaderboard     # noqa: E402,F401  /user/<username>, /follow, /friends, /leaderboard
from routes import admin           # noqa: E402,F401  /admin/*
from routes import reports         # noqa: E402,F401  /weekly_report, /weekly_csv, /api/weekly_report
from routes import contest         # noqa: E402,F401  /student_contest, /contest/* (Contest Tracker, Phase 1)
from routes import analytics       # noqa: E402,F401  (Phase 3 — currently empty, see file docstring)
from routes import notifications   # noqa: E402,F401  (Phase 3 — currently empty, see file docstring)
from routes import api             # noqa: E402,F401  (Phase 3 — currently empty, see file docstring)


# ── Error handlers ────────────────────────────────────────────────────────────
from flask import render_template


@app.errorhandler(404)
def e404(e):
    return render_template("error.html", code=404, msg="Page not found."), 404


@app.errorhandler(403)
def e403(e):
    return render_template("error.html", code=403, msg="Access denied."), 403


@app.errorhandler(429)
def e429(e):
    return render_template("error.html", code=429, msg="Too many requests."), 429


# ── Background workers (auto-sync scheduler + contest-sync scheduler) ────────
# IMPORTANT: this used to live inside `if __name__ == "__main__":` at the
# bottom of this file, which means it only ever ran under `python app.py` —
# under gunicorn (`gunicorn app:app`, what Procfile/render.yaml actually use
# in production) that block never executes at all, so neither the per-user
# auto-sync scheduler nor the contest-result scheduler ever started in
# production. That's the root cause behind the Phase 6 audit's Issue 1
# ("contest end detect pannala") — there was no live process checking for
# it. Moved to module level (still with a call to ensure_db_columns() /
# ensure_tracker_schema() first) so it runs on import — under gunicorn
# directly, and under the Werkzeug reloader's actual serving child process
# (guarded below so the reloader's parent watcher process doesn't also
# start a duplicate copy).
def _running_under_gunicorn():
    return "gunicorn" in sys.argv[0]


if _running_under_gunicorn() or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    from database.db import ensure_db_columns
    from workers.sync_worker import start_sync_worker
    from workers.contest_worker import start_contest_worker
    from config import Config

    ensure_db_columns()
    ensure_tracker_schema()
    start_sync_worker()
    if Config.CONTEST_AUTO_SYNC_ENABLED:
        start_contest_worker()
    else:
        print("[app] Contest auto-sync is disabled (CONTEST_AUTO_SYNC_ENABLED=false in .env). "
              "Use the admin 'Sync Now' button for manual syncing.")


if __name__ == "__main__":
    app.run(debug=True)
