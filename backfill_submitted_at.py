"""
backfill_submitted_at.py — one-off fix for historical submissions rows
that were inserted before migration 0007 added submitted_at (so it's NULL
today), or that got stuck NULL from a since-fixed insert path.

Run this ONCE, manually, after deploying the 0008 migration + the
normal_sync.py / bot_sheet_sync.py self-heal fix:

    python backfill_submitted_at.py

What it does:
    - Finds every submissions row with submitted_at IS NULL.
    - Re-fetches that user's CF/AC submissions (both APIs return full
      history for free, keyed by handle) and matches by problem_id to
      recover the REAL solve time, instead of guessing.
    - LeetCode has no reliable full-history public endpoint in this app
      (see normal_sync.py's fetch_lc — only last 20, best-effort), so
      LeetCode rows that can't be matched are left NULL and printed out
      for manual review; they will keep being excluded from contest
      grading until fixed by hand or a real submission timestamp shows up
      via a future sync of that exact problem.
    - Never overwrites a submitted_at that's already set.

Safe to re-run; only ever touches rows that are still NULL.
"""

from collections import defaultdict

from database.db import get_db
from normal_sync import fetch_cf, fetch_ac


def _index_by_problem_id(rows):
    """rows are the 8-element lists normal_sync.py's fetchers return —
    index 7 is submitted_at, but we need the problem_id, which isn't in
    that shape directly, so re-derive it the same way normal_sync.py's
    insert loop does."""
    idx = {}
    for row in rows:
        problem_url = row[1].split('"')[1] if '"' in row[1] else row[2]
        if "leetcode.com/problems/" in problem_url:
            pid = problem_url.split("/problems/")[-1].split("/")[0]
        elif "codeforces.com/problemset/problem" in problem_url:
            parts = problem_url.split("/")
            pid = parts[-2] + "-" + parts[-1]
        elif "atcoder.jp/contests" in problem_url:
            pid = problem_url.split("/")[-1]
        else:
            pid = problem_url
        idx[pid] = row[7]  # submitted_at
    return idx


def main():
    with get_db() as db:
        null_rows = db.execute("""
            SELECT s.id, s.user_id, s.platform, s.problem_id,
                   u.cf_handle, u.ac_handle
            FROM submissions s
            JOIN users u ON u.id = s.user_id
            WHERE s.submitted_at IS NULL
        """).fetchall()

    if not null_rows:
        print("Nothing to backfill — no NULL submitted_at rows found.")
        return

    print(f"Found {len(null_rows)} row(s) with NULL submitted_at.")

    by_user = defaultdict(list)
    for r in null_rows:
        by_user[r["user_id"]].append(r)

    fixed, unfixable = 0, []

    for user_id, rows in by_user.items():
        cf_handle = rows[0]["cf_handle"]
        ac_handle = rows[0]["ac_handle"]

        cf_index = _index_by_problem_id(fetch_cf(cf_handle)) if cf_handle else {}
        ac_index = _index_by_problem_id(fetch_ac(ac_handle)) if ac_handle else {}

        with get_db() as db:
            for r in rows:
                lookup = cf_index if r["platform"] == "Codeforces" else \
                    ac_index if r["platform"] == "AtCoder" else {}
                submitted_at = lookup.get(r["problem_id"])

                if not submitted_at:
                    unfixable.append((r["id"], r["platform"], r["problem_id"]))
                    continue

                db.execute(
                    "UPDATE submissions SET submitted_at=? WHERE id=? AND submitted_at IS NULL",
                    (submitted_at, r["id"]),
                )
                fixed += 1
            db.commit()

    print(f"\nBackfilled {fixed} row(s).")
    if unfixable:
        print(f"{len(unfixable)} row(s) could not be matched (likely LeetCode, "
              f"or a solve outside CF/AC's returned history) — left NULL, review manually:")
        for sid, platform, pid in unfixable[:50]:
            print(f"  submissions.id={sid}  platform={platform}  problem_id={pid}")


if __name__ == "__main__":
    main()
