"""
routes/dashboard.py — the main user dashboard, and the two "mark complete"
actions on it (daily challenge, mentor assignment). Moved verbatim from
app.py.
"""

from flask import render_template, jsonify
from flask_login import current_user

from extensions import app
from database.db import get_db
from utils.decorators import login_required, verified_required
from utils.helpers import get_counts
from services.sync_engine import get_dashboard_data, generate_daily_challenges


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
@verified_required
def dashboard():
    with get_db() as db:
        subs = db.execute(
            "SELECT * FROM submissions WHERE user_id=? ORDER BY solved_date DESC",
            (current_user.id,)
        ).fetchall()

        fol_count = db.execute(
            "SELECT COUNT(*) as c FROM follows WHERE follower_id=?",
            (current_user.id,)
        ).fetchone()["c"]

        fwg_count = db.execute(
            "SELECT COUNT(*) as c FROM follows WHERE following_id=?",
            (current_user.id,)
        ).fetchone()["c"]

        sync_log = db.execute(
            "SELECT * FROM sync_logs WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (current_user.id,)
        ).fetchone()

    # MAIN DATA
    data = get_dashboard_data(subs)

    # ADD COUNTS
    total, solved = get_counts(current_user.id)
    data["total"] = total
    data["solved"] = solved

    # EXTRA DATA
    data["following_count"] = fol_count
    data["follower_count"] = fwg_count
    data["last_sync_msg"] = dict(sync_log) if sync_log else None

    # Daily challenges
    challenges = generate_daily_challenges(current_user.id, get_db)

    # Mentor tasks
    with get_db() as db:
        mentor_tasks = db.execute(
            "SELECT * FROM mentor_assignments WHERE user_id=? AND completed=0",
            (current_user.id,)
        ).fetchall()

    # Sheet URL
    sheet_url = None
    if current_user.sheet_id and current_user.sheet_id.strip():
        sheet_url = f"https://docs.google.com/spreadsheets/d/{current_user.sheet_id}"

    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE id=?",
            (current_user.id,)
        ).fetchone()

    return render_template(
        "dashboard.html",
        user=user,
        data=data,
        challenges=challenges,
        mentor_tasks=mentor_tasks,
        sheet_url=sheet_url
    )


# ── Mark challenge complete ────────────────────────────────────────────────────
@app.route("/challenge/complete/<int:cid>", methods=["POST"])
@login_required
@verified_required
def complete_challenge(cid):
    with get_db() as db:
        db.execute(
            "UPDATE daily_challenges SET completed=1 WHERE id=? AND user_id=?",
            (cid, current_user.id)
        )
        db.commit()
    return jsonify({"success": True})


@app.route("/mentor/complete/<int:mid>", methods=["POST"])
@login_required
@verified_required
def complete_mentor(mid):
    with get_db() as db:
        db.execute(
            "UPDATE mentor_assignments SET completed=1 WHERE id=? AND user_id=?",
            (mid, current_user.id)
        )
        db.commit()
    return jsonify({"success": True})
