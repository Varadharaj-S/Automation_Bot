"""
routes/contest.py — Phase 1 of the Contest Tracker: the /student_contest
dashboard, contest create/edit/delete, and /contest/history. No Google
Sheets integration (Phase 2) and no platform sync (Phase 3) yet — status
is computed live from date/time (see contest.contest_utils.compute_status),
not driven by a scheduler, since there isn't one yet.

Access note: the design doc asks for "Admin and Mentor" access, but this
codebase doesn't actually have a separate mentor role — "Mentor Mode"
(routes/admin.py's /admin/mentor) is itself an admin-only page. Contest
routes are gated the same way, behind admin_required, until/unless a real
mentor role gets added.
"""

from datetime import datetime
import re

from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user

from extensions import app
from utils.decorators import login_required, admin_required, log_admin
from utils.security import sanitize
from contest import contest_service
from contest import contest_sheet
from contest import contest_sync
from contest.contest_utils import (
    extract_contest_code,
    generate_problem_list,
    fetch_codeforces_problem_letters,
)


@app.route("/student_contest")
@login_required
@admin_required
def student_contest():
    contests = contest_service.list_contests()
    counts = {"Upcoming": 0, "Running": 0, "Completed": 0}
    for c in contests:
        counts[c["status"]] = counts.get(c["status"], 0) + 1

    return render_template(
        "contest_dashboard.html",
        contests=contests,
        counts=counts,
        total_contests=len(contests),
    )


@app.route("/contest/create", methods=["GET", "POST"])
@login_required
@admin_required
def contest_create():
    if request.method == "POST":
        name = sanitize(request.form.get("contest_name", ""), 120)
        code = sanitize(request.form.get("contest_code", ""), 32)
        platform = request.form.get("platform", "Codeforces")
        contest_date = request.form.get("contest_date", "")
        start_time = request.form.get("start_time", "")
        end_time = request.form.get("end_time", "")
        contest_url = sanitize(request.form.get("contest_url", ""), 300)
        problems_raw = request.form.get("problems", "")
        problems = [p for p in re.split(r"[,\s]+", problems_raw.strip()) if p]

        # Auto-fill from the pasted Contest URL — no manual A,B,C,D typing
        # needed for AtCoder, and no manual contest-code copying needed for
        # Codeforces either. Only fills in what the admin left blank;
        # anything they typed by hand is always respected as-is.
        auto_note = ""
        if contest_url and platform in ("AtCoder", "Codeforces"):
            if not code:
                extracted = extract_contest_code(platform, contest_url)
                if extracted:
                    code = extracted
                    auto_note += f" Contest Code auto-filled as '{code}' from the URL."
            if not problems:
                if platform == "AtCoder":
                    generated = generate_problem_list(platform, code)
                elif platform == "Codeforces" and code:
                    # One-time live lookup at creation time only — not
                    # part of the sync path (see fetch_codeforces_problem_
                    # letters' docstring). [] on any failure, admin just
                    # types them manually then, same as before.
                    generated = fetch_codeforces_problem_letters(code)
                else:
                    generated = []
                if generated:
                    problems = generated
                    auto_note += (
                        f" Problem list auto-{'generated' if platform == 'AtCoder' else 'fetched from Codeforces'} "
                        f"({', '.join(problems)})."
                    )
                elif platform == "Codeforces" and code:
                    auto_note += (
                        " Couldn't fetch the problem list from Codeforces automatically "
                        "(CF unreachable or contest not found) — add problems manually below."
                    )

        if not (name and code and contest_date and start_time and end_time):
            flash("All fields are required.", "error")
            return redirect(url_for("contest_create"))

        if platform not in ("Codeforces", "LeetCode", "AtCoder"):
            flash("Invalid platform.", "error")
            return redirect(url_for("contest_create"))

        # Issue 15: input validation on contest create
        if contest_url and not re.match(r"^https?://", contest_url):
            flash("Contest URL must start with http:// or https://", "error")
            return redirect(url_for("contest_create"))

        try:
            datetime.strptime(contest_date, "%Y-%m-%d")
            datetime.strptime(start_time, "%H:%M")
            datetime.strptime(end_time, "%H:%M")
        except ValueError:
            flash("Invalid date or time format.", "error")
            return redirect(url_for("contest_create"))

        if end_time == start_time:
            flash("End time must be different from start time.", "error")
            return redirect(url_for("contest_create"))

        row, error = contest_service.create_contest(
            name, code, platform, contest_date, start_time, end_time, current_user.id,
            contest_url=contest_url, problems=problems,
        )
        if error:
            flash(error, "error")
            return redirect(url_for("contest_create"))

        log_admin("create_contest", target=code, details=name)

        sheet_ok, sheet_msg = contest_sheet.ensure_sheet_for_contest(dict(row))
        problems_note = f" {len(problems)} problem(s) saved." if problems else \
            " No problems added yet — add them before this contest can be synced."
        problems_note += auto_note
        if sheet_ok:
            flash(f"Contest '{name}' created.{problems_note} {sheet_msg}", "success")
        else:
            # Contest exists in Postgres either way — Sheets failure is
            # surfaced but non-fatal, same pattern as email failures
            # elsewhere in this app not blocking signup.
            flash(f"Contest '{name}' created,{problems_note} but {sheet_msg} "
                  f"Use 'Refresh Sheet' on the dashboard once fixed.", "warning")
        return redirect(url_for("student_contest"))

    return render_template("contest_create.html")


@app.route("/contest/edit/<int:cid>", methods=["POST"])
@login_required
@admin_required
def contest_edit(cid):
    c = contest_service.get_contest(cid)
    if not c:
        flash("Contest not found.", "error")
        return redirect(url_for("student_contest"))

    contest_service.update_contest(
        cid,
        contest_name=sanitize(request.form.get("contest_name", ""), 120) or None,
        platform=request.form.get("platform") or None,
        contest_date=request.form.get("contest_date") or None,
        start_time=request.form.get("start_time") or None,
        end_time=request.form.get("end_time") or None,
    )
    contest_service.sync_status_column(cid)
    log_admin("edit_contest", target=c["contest_code"])
    flash("Contest updated.", "success")
    return redirect(url_for("student_contest"))


@app.route("/contest/<int:cid>/add_problems", methods=["POST"])
@login_required
@admin_required
def contest_add_problems(cid):
    """Append more problems to an existing contest (e.g. the admin forgot
    one at creation, or the contest had more rounds/problems than
    expected). Safe to call repeatedly — duplicates are ignored."""
    c = contest_service.get_contest(cid)
    if not c:
        flash("Contest not found.", "error")
        return redirect(url_for("student_contest"))

    problems_raw = request.form.get("problems", "")
    problems = [p for p in re.split(r"[,\s]+", problems_raw.strip()) if p]

    auto_note = ""
    if not problems and c["platform"] == "Codeforces" and c["contest_code"]:
        problems = fetch_codeforces_problem_letters(c["contest_code"])
        if problems:
            auto_note = f" (auto-fetched from Codeforces: {', '.join(problems)})"

    if not problems:
        flash("No problem codes entered, and auto-fetch from Codeforces didn't return "
              "anything — type them in manually.", "error")
        return redirect(url_for("student_contest"))

    saved = contest_service.add_problems(cid, c["platform"], c["contest_code"], problems)
    log_admin("add_contest_problems", target=c["contest_code"], details=f"{saved} problem(s)")
    flash(f"{saved} problem(s) saved for '{c['contest_name']}'.{auto_note}", "success")
    return redirect(url_for("student_contest"))


@app.route("/contest/delete/<int:cid>", methods=["POST"])
@login_required
@admin_required
def contest_delete(cid):
    c = contest_service.get_contest(cid)
    if c:
        contest_service.delete_contest(cid)
        log_admin("delete_contest", target=c["contest_code"])
        flash(f"Contest '{c['contest_name']}' deleted.", "success")
    return redirect(url_for("student_contest"))


@app.route("/contest/history")
@login_required
@admin_required
def contest_history():
    contests = contest_service.list_contests(status="Completed")
    return render_template("contest_history.html", contests=contests)


@app.route("/contest/refresh_sheet", methods=["POST"])
@login_required
@admin_required
def contest_refresh_sheet():
    ok, msg = contest_sheet.refresh_sheet()
    flash(msg, "success" if ok else "error")
    log_admin("refresh_contest_sheet", details=msg)
    return redirect(url_for("student_contest"))


# ── Phase 3: manual result sync (AJAX, mirrors admin.py's per-user sync button) ─
@app.route("/contest/sync_now/<int:cid>", methods=["POST"])
@login_required
@admin_required
def contest_sync_now(cid):
    c = contest_service.get_contest(cid)
    if not c:
        return jsonify({"ok": False, "message": "Contest not found"}), 404
    if c["status"] != "Completed":
        return jsonify({"ok": False, "message": f"Contest is still '{c['status']}' — nothing to sync yet."}), 400

    contest_service.force_resync(cid)
    ok, msg = contest_sync.sync_one_contest(c)
    log_admin("contest_sync_now", target=c["contest_code"], details=msg)
    return jsonify({"ok": ok, "message": msg})


@app.route("/contest/leaderboard")
@login_required
@admin_required
def contest_leaderboard():
    rows = contest_service.get_leaderboard()
    return render_template("contest_leaderboard.html", rows=rows)
