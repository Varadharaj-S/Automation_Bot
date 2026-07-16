"""
utils/helpers.py — small, stateless helpers used by several route modules.
Moved verbatim from app.py.
"""

from datetime import datetime

from flask_login import current_user

from database.db import get_db


def get_counts(user_id):
    with get_db() as conn:
        row = conn.execute("""
            SELECT COUNT(DISTINCT problem_id) AS cnt
            FROM submissions
            WHERE user_id=?
        """, (user_id,)).fetchone()
    total = (row["cnt"] if row else 0) or 0

    # solved = all rows (already solved submissions)
    return total, total


def _parse_any_date(value):
    """Parse dates stored in multiple formats used by the app."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    fmts = ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%y")
    for fmt in fmts:
        try:
            return datetime.strptime(s[:10], fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _date_label(dt_obj, fallback="Unknown"):
    if not dt_obj:
        return fallback
    return dt_obj.strftime("%d-%m-%Y")


def _clean_topic(topic):
    return " ".join(str(topic or "").split()).strip()


def _group_rows(rows, include_username=False):
    """Return grouped daily rows from submission rows."""
    groups = {}
    for row in rows:
        dt = _parse_any_date(row["solved_date"])
        date_label = _date_label(dt, str(row["solved_date"] or "Unknown"))

        username = row["username"] if include_username and "username" in row.keys() else current_user.username
        key = (date_label, username)

        if key not in groups:
            groups[key] = {
                "date": date_label,
                "date_dt": dt or datetime.min,
                "username": username,
                "solved_count": 0,
                "easy": 0,
                "medium": 0,
                "hard": 0,
                "problems": []
            }

        item = groups[key]
        item["solved_count"] += 1
        diff = str(row["difficulty"] or "").strip().lower()
        if diff == "easy":
            item["easy"] += 1
        elif diff == "medium":
            item["medium"] += 1
        elif diff == "hard":
            item["hard"] += 1

        item["problems"].append({
            "name": row["problem_name"] or "",
            "url": row["problem_url"] or "",
            "difficulty": row["difficulty"] or "",
            "platform": row["platform"] or "",
            "topic": row["tags"] or row["topic"] if "topic" in row.keys() else (row["tags"] or "")
        })

    # Sort: latest date first, then count desc, then username
    ordered = sorted(
        groups.values(),
        key=lambda x: (
            x["date_dt"] if x["date_dt"] != datetime.min else datetime.min,
            x["solved_count"],
            x["username"].lower()
        ),
        reverse=True
    )
    return ordered


def _get_user_by_username(username):
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return row
