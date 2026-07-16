"""
contest/contest_utils.py — small stateless helpers shared across the
contest module. Phase 1 scope: just status computation and code
normalization. Platform-specific parsing helpers land here in Phase 3.
"""

import re
from datetime import datetime, date, time as time_cls, timedelta

import requests


def compute_status(contest_date, start_time, end_time, now=None):
    """
    Returns 'Upcoming' | 'Running' | 'Completed' given a contest's date and
    start/end times. Computed fresh on every read rather than trusted from
    the stored column, the same pattern services/tracker_service.py uses
    for daily_tracker_sheet_results — status always reflects the current
    time, never goes stale waiting for a scheduler run (Phase 3).
    """
    now = now or datetime.now()

    if isinstance(contest_date, str):
        contest_date = datetime.strptime(contest_date, "%Y-%m-%d").date()
    if isinstance(start_time, str):
        start_time = datetime.strptime(start_time, "%H:%M").time()
    if isinstance(end_time, str):
        end_time = datetime.strptime(end_time, "%H:%M").time()

    start_dt = datetime.combine(contest_date, start_time)
    end_dt = datetime.combine(contest_date, end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)  # crosses midnight

    if now < start_dt:
        return "Upcoming"
    if start_dt <= now <= end_dt:
        return "Running"
    return "Completed"


def normalize_contest_code(code):
    """Contest codes are used as Google Sheet column headers (Phase 2) and
    as a unique key, so keep them short and predictable: alnum + dash/underscore."""
    code = re.sub(r"[^A-Za-z0-9_-]", "", str(code or "").strip())
    return code[:32]


# ── DB-only contest sync (no platform APIs) ───────────────────────────────────
def get_contest_window(contest):
    """
    Returns (start_dt, end_dt) as naive local datetimes for a contest's
    solve window — used to filter submissions.submitted_at with a plain
    SQL BETWEEN (see contest/contest_sync.py). Handles a contest that
    crosses midnight the same way compute_status() does: if end_time is
    not after start_time on the same date, the end is treated as the
    next day.
    """
    contest_date = contest["contest_date"]
    start_time = contest["start_time"]
    end_time = contest["end_time"]

    if isinstance(contest_date, str):
        contest_date = datetime.strptime(contest_date, "%Y-%m-%d").date()
    if isinstance(start_time, str):
        start_time = datetime.strptime(start_time, "%H:%M").time()
    if isinstance(end_time, str):
        end_time = datetime.strptime(end_time, "%H:%M").time()

    start_dt = datetime.combine(contest_date, start_time)
    end_dt = datetime.combine(contest_date, end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def normalize_problem_code(platform, contest_code, raw):
    """
    Turns whatever an admin typed for one contest problem (usually just a
    letter, e.g. "A" or "D2") into the exact same string format
    normal_sync.py's sync_user_data() stores as submissions.problem_id for
    that platform, so contest_sync.py's DB join actually matches:

      AtCoder:     "A"  -> "{contest_code}_a"   (lowercase, e.g. "abc466_a")
      Codeforces:  "B"  -> "{contest_code}-B"   (contest_code is the numeric
                           contest id, e.g. "2246", giving "2246-B")
      LeetCode:    used as typed — LeetCode problems don't have a per-contest
                   letter scheme in this app, admins type the full slug
                   (e.g. "two-sum").

    If the admin already typed the full code (contains the platform's own
    separator), it's kept as-is rather than double-prefixed.
    """
    raw = str(raw or "").strip()
    if not raw:
        return ""

    if platform == "AtCoder":
        if "_" in raw:
            return raw.lower()
        return f"{contest_code.lower()}_{raw.lower()}"

    if platform == "Codeforces":
        if "-" in raw:
            return raw
        return f"{contest_code}-{raw.upper()}"

    # LeetCode (and any future platform): no reliable letter -> slug mapping,
    # so store exactly what was typed.
    return raw


# ── Auto-generation from a pasted Contest URL (no more manual A,B,C,D typing) ──

ATCODER_URL_RE = re.compile(r"atcoder\.jp/contests/([a-zA-Z0-9_-]+)")
CODEFORCES_URL_RE = re.compile(r"codeforces\.com/(?:contest|contestRegistration|problemset/problem)/(\d+)")

# AtCoder contest types don't all have the same letter range (ABC has had
# A-G since round ~212; older/other formats vary) — this is a best-effort
# default the admin can still edit via "Add Problems" afterward, not a
# guarantee of the exact set for every single contest.
ATCODER_DEFAULT_LETTERS = {
    "abc": list("abcdefg"),
    "arc": list("abcdef"),
    "agc": list("abcdef"),
}


def extract_contest_code(platform, contest_url):
    """Pulls the platform's own contest id straight out of a pasted URL,
    e.g. "https://atcoder.jp/contests/abc466" -> "abc466", or
    "https://codeforces.com/contest/2244" -> "2244". Returns "" if the URL
    doesn't match a known pattern — caller should fall back to asking for
    the Contest Code field manually."""
    if platform == "AtCoder":
        m = ATCODER_URL_RE.search(contest_url or "")
        return m.group(1) if m else ""
    if platform == "Codeforces":
        m = CODEFORCES_URL_RE.search(contest_url or "")
        return m.group(1) if m else ""
    # LeetCode contest URLs already ARE the slug admins type as the
    # Contest Code today — no separate extraction needed.
    return ""


def generate_problem_list(platform, contest_code):
    """contest_code -> list of raw problem letters (e.g. ["A","B","C",...])
    ready to hand straight to contest_service.add_problems(), which will
    run each one through normalize_problem_code() itself. Best-effort only
    for AtCoder today; returns [] for platforms with no reliable static
    default (Codeforces uses fetch_codeforces_problem_letters() below
    instead, since CF varies too much by round type to guess)."""
    if platform != "AtCoder" or not contest_code:
        return []
    prefix_match = re.match(r"[a-zA-Z]+", contest_code)
    prefix = prefix_match.group(0).lower() if prefix_match else ""
    letters = ATCODER_DEFAULT_LETTERS.get(prefix, list("abcdef"))
    return [ltr.upper() for ltr in letters]


def fetch_codeforces_problem_letters(contest_id, timeout=10):
    """
    Looks up the REAL problem list for one specific Codeforces contest via
    CF's public contest.standings API — no guessing, since CF's problem
    count varies too much by round type (Div1/2/3/4, Educational, etc.)
    for a static default like AtCoder's to be reliable.

    IMPORTANT — this is a ONE-TIME lookup at contest CREATION time only,
    called from routes/contest.py, never from contest/contest_sync.py.
    It does not violate the "no live API calls during contest sync"
    design (see contest_sync.py's module docstring) — that rule is about
    GRADING (comparing students' solves against the DB), which stays
    100% DB-only. This is just a one-off convenience so the admin doesn't
    have to go look up and type the problem letters by hand; if it fails
    or CF is unreachable, it returns [] and the admin types them manually,
    same as before this existed.

    Returns a list like ["A", "B", "C", "D", "E", "F"], or [] on any
    failure (bad contest id, CF down, network error, unexpected shape).
    """
    try:
        resp = requests.get(
            "https://codeforces.com/api/contest.standings",
            params={"contestId": contest_id},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        if data.get("status") != "OK":
            return []
        problems = data.get("result", {}).get("problems", [])
        letters = [p["index"] for p in problems if p.get("index")]
        return letters
    except Exception:
        return []
