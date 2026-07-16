"""
database/fix_orphans.py — one-off cleanup for rows left behind by users
that were deleted before migration 0001's foreign keys existed to stop it.

These are all "child" rows pointing at a user_id that no longer exists in
`users` — safe to delete, they're dead data belonging to an account that's
already gone. Run this ONCE, then re-run migrate.py.

Usage:
    python database/fix_orphans.py            # shows what it would delete
    python database/fix_orphans.py --apply    # actually deletes it
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_db  # noqa: E402

CLEANUPS = [
    ("login_history", "user_id",
     "DELETE FROM login_history WHERE user_id IS NOT NULL AND user_id NOT IN (SELECT id FROM users)"),
    ("daily_challenges", "user_id",
     "DELETE FROM daily_challenges WHERE user_id NOT IN (SELECT id FROM users)"),
    ("email_tokens", "user_id",
     "DELETE FROM email_tokens WHERE user_id NOT IN (SELECT id FROM users)"),
    ("daily_tracker_sheet_results", "student_id",
     "DELETE FROM daily_tracker_sheet_results WHERE student_id NOT IN (SELECT id FROM users)"),
]


def main():
    apply = "--apply" in sys.argv
    db = get_db()
    try:
        for table, col, delete_sql in CLEANUPS:
            count_sql = delete_sql.replace("DELETE FROM", "SELECT COUNT(*) AS n FROM", 1)
            n = db.execute(count_sql).fetchone()["n"]
            print(f"{table} ({col}): {n} orphaned row(s)")
            if apply and n:
                db.execute(delete_sql)
        if apply:
            db.commit()
            print("\nDeleted. Now re-run: python database/migrate.py")
        else:
            print("\nDry run only. Re-run with --apply to actually delete these rows.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
