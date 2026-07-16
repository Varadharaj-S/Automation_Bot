"""
contest/contest_service.py — Phase 1 scope: contest CRUD against
PostgreSQL only. No Google Sheets (contest_sheet.py, Phase 2), no
platform API calls (contest_api.py / contest_sync.py, Phase 3).

Every function takes plain values in / returns plain dict-like DB rows
out — routes/contest.py is the only caller and does its own sanitize()
on form input before it reaches here, matching the pattern the rest of
the app already uses (routes sanitize, services trust their callers).
"""

from database.db import get_db
from contest.contest_utils import compute_status, normalize_contest_code, normalize_problem_code


def create_contest(contest_name, contest_code, platform, contest_date,
                    start_time, end_time, created_by, contest_url="", problems=None):
    """
    problems: optional list of raw problem codes as typed by the admin
    (e.g. ["A", "B", "C", "D"]). Normalized via
    contest_utils.normalize_problem_code() and saved to contest_problems —
    this is the list contest_sync.py grades against once the contest ends,
    no platform API involved. A contest with no problems saved is still
    created (so admins can add them later via add_problems()), but
    contest_sync.py will refuse to sync it until at least one exists.
    """
    contest_code = normalize_contest_code(contest_code)
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM contest_events WHERE contest_code=?", (contest_code,)
        ).fetchone()
        if existing:
            return None, f"Contest code '{contest_code}' already exists."

        # Issue 8: dedupe by URL too, since a typo'd code can otherwise
        # let the same real-world contest get created twice.
        if contest_url:
            url_clash = db.execute(
                "SELECT id FROM contest_events WHERE contest_url=? AND contest_url != ''",
                (contest_url,)
            ).fetchone()
            if url_clash:
                return None, "A contest with this URL already exists."

        db.execute("""
            INSERT INTO contest_events
            (contest_name, contest_code, platform, contest_date, start_time, end_time,
             status, sheet_name, created_by, contest_url)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (contest_name, contest_code, platform, contest_date, start_time, end_time,
              compute_status(contest_date, start_time, end_time),
              "Student_Contest", created_by, contest_url))
        db.commit()

        row = db.execute(
            "SELECT * FROM contest_events WHERE contest_code=?", (contest_code,)
        ).fetchone()

    if problems and row:
        try:
            add_problems(row["id"], platform, contest_code, problems)
        except Exception as e:
            # Contest itself is already committed (see the closed `with
            # get_db()` block above) — don't let a problems-save failure
            # look like the whole create failed. Surface it instead of
            # letting it 500.
            return row, f"Contest '{contest_name}' created, but problems failed to save: {e}"

    return row, None


def add_problems(contest_id, platform, contest_code, raw_codes):
    """
    raw_codes: list of strings as typed by the admin (letters like "A", "B"
    for AtCoder/Codeforces, or full slugs for LeetCode). Each is normalized
    to match submissions.problem_id's format for that platform (see
    contest_utils.normalize_problem_code) so contest_sync.py's DB join
    against already-collected submissions actually finds them. Safe to call
    again later to add more problems — duplicates are ignored.
    Returns the number of problems saved (including ones that already existed).
    """
    seen = set()
    to_insert = []
    for raw in raw_codes:
        code = normalize_problem_code(platform, contest_code, raw)
        if code and code not in seen:
            seen.add(code)
            to_insert.append((code, str(raw).strip()))

    if not to_insert:
        return 0

    with get_db() as db:
        for code, raw in to_insert:
            db.execute("""
                INSERT INTO contest_problems (
                    contest_id,
                    platform,
                    problem_id,
                    problem_name
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT (contest_id, problem_id) DO NOTHING
            """, (contest_id, platform, code, raw))
        db.commit()
    return len(to_insert)


def get_contest_problems(contest_id):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM contest_problems WHERE contest_id=? ORDER BY id ASC", (contest_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def list_contests(status=None):
    """Returns all contests, freshest first, with status recomputed live
    (not trusted from the stored column — see contest_utils.compute_status)."""
    with get_db() as db:
        rows = db.execute("""
            SELECT ce.*, COALESCE(pc.cnt, 0) AS problem_count
            FROM contest_events ce
            LEFT JOIN (
                SELECT contest_id, COUNT(*) AS cnt FROM contest_problems GROUP BY contest_id
            ) pc ON pc.contest_id = ce.id
            ORDER BY ce.contest_date DESC, ce.start_time DESC
        """).fetchall()

    contests = []
    for r in rows:
        d = dict(r)
        d["status"] = compute_status(d["contest_date"], d["start_time"], d["end_time"])
        contests.append(d)

    if status:
        contests = [c for c in contests if c["status"] == status]
    return contests


def get_contest(contest_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM contest_events WHERE id=?", (contest_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["status"] = compute_status(d["contest_date"], d["start_time"], d["end_time"])
    return d


def update_contest(contest_id, contest_name=None, platform=None,
                    contest_date=None, start_time=None, end_time=None):
    fields, params = [], []
    for col, val in [("contest_name", contest_name), ("platform", platform),
                      ("contest_date", contest_date), ("start_time", start_time),
                      ("end_time", end_time)]:
        if val is not None:
            fields.append(f"{col}=?")
            params.append(val)
    if not fields:
        return False
    params.append(contest_id)
    with get_db() as db:
        db.execute(f"UPDATE contest_events SET {', '.join(fields)} WHERE id=?", params)
        db.commit()
    return True


def delete_contest(contest_id):
    with get_db() as db:
        db.execute("DELETE FROM contest_events WHERE id=?", (contest_id,))
        db.commit()


def sync_status_column(contest_id):
    """Persist the freshly-computed status onto the stored column, so
    other tools reading the table directly (e.g. a future Sheet formula
    or a report query) see an up-to-date value too. Routes call this
    after create/edit; Phase 3's scheduler calls it as contests transition
    into 'Running'/'Completed'."""
    c = get_contest(contest_id)
    if not c:
        return
    with get_db() as db:
        db.execute("UPDATE contest_events SET status=? WHERE id=?", (c["status"], contest_id))
        db.commit()


# ── Phase 3: automatic result sync (Issue 1) ──────────────────────────────────
def get_due_contests():
    """Every contest whose computed status is 'Completed' but hasn't been
    synced yet — what contest_sync.run_due_contests() processes each tick.
    Status is computed live (never trusted from the stored column) so a
    contest becomes 'due' the instant its end_time passes, not whenever
    something last called sync_status_column().

    Contests that failed their last attempt within the last
    Config.CONTEST_SYNC_INTERVAL_MINUTES are skipped for this tick — a
    contest that's genuinely unreachable (e.g. wrong contest_code, or an
    AtCoder contest that needs sign-in) shouldn't get hammered every 5
    minutes; MAX_SYNC_ATTEMPTS in contest_sync.py still caps it at 5
    tries total, this just spaces them out. Manual "Sync Now" bypasses
    this entirely (it calls sync_one_contest directly, not this list)."""
    from config import Config
    cooldown_minutes = Config.CONTEST_SYNC_INTERVAL_MINUTES

    with get_db() as db:
        rows = db.execute("""
            SELECT * FROM contest_events
            WHERE synced=FALSE
              AND (last_attempt_at IS NULL OR last_attempt_at < now() - (? || ' minutes')::interval)
        """, (str(cooldown_minutes),)).fetchall()
    due = []
    for r in rows:
        d = dict(r)
        d["status"] = compute_status(d["contest_date"], d["start_time"], d["end_time"])
        if d["status"] == "Completed":
            due.append(d)
    return due


def force_resync(contest_id):
    """Admin 'Sync Now' button: clears synced + any stuck claim so the next
    sync call reprocesses this contest, even if it previously gave up after
    MAX_SYNC_ATTEMPTS. Does not reset sync_attempts — the retry count keeps
    counting so persistent failures stay visible in the history."""
    with get_db() as db:
        db.execute(
            "UPDATE contest_events SET synced=FALSE, sync_claimed_at=NULL WHERE id=?",
            (contest_id,)
        )
        db.commit()


def get_sync_logs(contest_id, limit=20):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM contest_sync_log WHERE contest_id=? ORDER BY created_at DESC LIMIT ?",
            (contest_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_results(contest_id):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM contest_results WHERE contest_id=? ORDER BY solved DESC, username ASC",
            (contest_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Phase 3: leaderboard (Issue 9) ────────────────────────────────────────────
def get_leaderboard(limit=50):
    """SUM(solved) GROUP BY user across every contest they've had a result
    row in, freshest-synced results included automatically (no separate
    'rebuild leaderboard' step — it's a live query, not a cached table)."""
    with get_db() as db:
        rows = db.execute("""
            SELECT u.id, u.username, u.full_name,
                   COALESCE(SUM(cr.solved), 0) AS total_solved,
                   COUNT(cr.id) FILTER (WHERE cr.attendance) AS contests_attended
            FROM users u
            LEFT JOIN contest_results cr ON cr.user_id = u.id
            WHERE u.status='active' AND u.is_admin=0
            GROUP BY u.id, u.username, u.full_name
            ORDER BY total_solved DESC, contests_attended DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]
