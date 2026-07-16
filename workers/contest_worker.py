"""
workers/contest_worker.py — starts the in-process contest-sync loop.

Same threading.Thread(daemon=True) approach as workers/sync_worker.py.
See services/contest_scheduler_service.py for why this exists alongside
the Render Cron job (contest_scheduler.py) rather than instead of it.
"""

import threading

from services.contest_scheduler_service import run_contest_scheduler


def start_contest_worker():
    """Start the contest-sync loop in a background daemon thread."""
    threading.Thread(target=run_contest_scheduler, daemon=True).start()
