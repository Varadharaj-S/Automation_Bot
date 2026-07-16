"""
config.py — application configuration, read from environment variables.

Same values the old app.py set inline on app.config; nothing here changes
behavior, it just gives them one home instead of being scattered at the top
of the monolith.
"""

import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv
load_dotenv()


class Config:
    # SECURITY: load from env, generate random fallback (never hardcoded).
    # NOTE: if SECRET_KEY isn't set, a new random key is generated every
    # process start, which invalidates existing sessions on restart — this
    # matches the original app.py behavior exactly. Set SECRET_KEY in your
    # environment for production so restarts don't log everyone out.
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Idle/inactivity timeout (fixes: open link should always show login,
    # back-button should not reveal a cached logged-in page after logout).
    IDLE_TIMEOUT_MINUTES = int(os.environ.get("IDLE_TIMEOUT_MINUTES", "20"))

    BACKUP_DIR = "backups"

    # ── Contest Tracker auto-sync (Phase 6) ───────────────────────────────
    # Master on/off switch for the background contest-result sync loop
    # (workers/contest_worker.py + contest_scheduler.py's cron). Set
    # CONTEST_AUTO_SYNC_ENABLED=false in .env to turn it off entirely while
    # testing/creating contests, and rely only on the admin "Sync Now"
    # button (routes/contest.py's /contest/sync_now/<id>) for manual,
    # on-demand syncing instead.
    CONTEST_AUTO_SYNC_ENABLED = os.environ.get("CONTEST_AUTO_SYNC_ENABLED", "true").lower() != "false"

    # How often the in-process loop ticks (minutes). Also how long a
    # contest that just failed is left alone before being retried again —
    # see contest/contest_sync.py's get_due_contests() cooldown.
    CONTEST_SYNC_INTERVAL_MINUTES = int(os.environ.get("CONTEST_SYNC_INTERVAL_MINUTES", "5"))
