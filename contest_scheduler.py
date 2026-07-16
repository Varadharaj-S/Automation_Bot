"""
contest_scheduler.py — Contest Tracker Phase 3 scheduler entry point
(Phase 6 audit, Issue 10).

Render Cron command:  python contest_scheduler.py
Schedule:              every 5 minutes (see render.yaml —
                        dsa-tracker-contest-sync)

Each run is one tick: find every Completed-but-unsynced contest and sync it
(contest.contest_sync.run_due_contests()), then exit. A cron job spawns a
fresh process per tick, so this deliberately does NOT loop internally —
same one-shot pattern as scheduler.py (the existing daily CF/LC/AC sync).

This is also exactly what extensions.py's in-process background thread
calls on the same 5-minute cadence (see contest/contest_sync.py's
run_due_contests() docstring) — that's a same-process safety net for
deployments that only run the web service and never set up the cron job;
this script is the reliable, dedicated-process way to run it in production.
Both are safe to run at once: contest_sync.py's atomic claim means only one
of them ever actually processes a given contest.

Environment variables (same as scheduler.py):
  DATABASE_URL         — PostgreSQL connection string (required)
  GOOGLE_SERVICE_JSON  — service account JSON string (for Sheets sync)
"""

import os
from datetime import datetime

from contest.contest_sync import run_due_contests
from config import Config


def _write_google_creds():
    """Write GOOGLE_SERVICE_JSON env var to file if not already on disk —
    same helper as scheduler.py. contest_sheet.py's _get_client() actually
    reads GOOGLE_SERVICE_JSON directly when set, so this is only needed as
    a fallback for local dev without the env var; harmless either way."""
    creds_json = os.environ.get("GOOGLE_SERVICE_JSON", "")
    creds_path = os.path.join(os.path.dirname(__file__), "google_creds.json")
    if creds_json and not os.path.exists(creds_path):
        try:
            with open(creds_path, "w") as f:
                f.write(creds_json)
        except Exception as e:
            print(f"[contest_scheduler] Could not write google_creds.json: {e}")


def main():
    start = datetime.now()
    print(f"\n{'='*55}")
    print(f"  Contest Tracker — Sync Tick  [{start.strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"{'='*55}\n")

    _write_google_creds()

    if not Config.CONTEST_AUTO_SYNC_ENABLED:
        print("[contest_scheduler] CONTEST_AUTO_SYNC_ENABLED=false — skipping this tick. "
              "Use the admin 'Sync Now' button for manual syncing.")
        return

    results = run_due_contests()
    if not results:
        print("[contest_scheduler] No completed/unsynced contests due.")
    else:
        ok_count = sum(1 for _, ok, _ in results if ok)
        print(f"\n[contest_scheduler] {ok_count}/{len(results)} contest(s) synced OK.")

    elapsed = (datetime.now() - start).seconds
    print(f"\n{'='*55}\n  Done ({elapsed}s)\n{'='*55}\n")


if __name__ == "__main__":
    main()
