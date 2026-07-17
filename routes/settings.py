"""
routes/settings.py — user account settings, the Chrome-extension cookie
endpoints, LeetCode browser-login connect, sync-time/auto-sync toggles,
and the feedback form. Moved verbatim from app.py.
"""

import os
import json
import time
from services.email_service import send_email

from flask import request, jsonify, render_template, redirect, url_for, flash
from flask_login import current_user
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import app
from database.db import get_db
from utils.decorators import login_required, verified_required
from utils.security import sanitize
from services.sync_engine import webdriver, Service, ChromeDriverManager


# ── User Settings ─────────────────────────────────────────────────────────────
@app.route("/save_settings", methods=["POST"])
@login_required
def save_settings():
    data = request.get_json() or {}

    with get_db() as db:
        db.execute("""
        UPDATE users SET
            lc_handle=?,
            cf_handle=?,
            ac_handle=?,
            lc_session_cookie=?,
            lc_csrf_token=?
        WHERE id=?
        """, (
            data.get("leetcode", ""),
            data.get("codeforces", ""),
            data.get("atcoder", ""),
            data.get("cookie", ""),
            data.get("csrf", ""),
            current_user.id
        ))

        db.commit()

    return jsonify({"status": "saved"})


# ── Chrome Extension: Save LeetCode Cookie ────────────────────────────────────
@app.route("/save_cookie", methods=["POST"])
@login_required
def save_cookie():
    """
    Called by the Chrome extension popup.
    Receives LEETCODE_SESSION and csrftoken and saves them for the logged-in user.
    """
    data = request.get_json(force=True) or {}
    lc_session = (data.get("leetcode_session") or "").strip()[:2000]
    csrf_token = (data.get("csrf_token") or "").strip()[:200]

    if not lc_session or not csrf_token:
        return jsonify({"success": False, "message": "Missing session or CSRF token"}), 400

    with get_db() as db:
        db.execute("""
            UPDATE users SET
                lc_session_cookie=?,
                lc_csrf_token=?,
                cookie_expiry=0
            WHERE id=?
        """, (lc_session, csrf_token, current_user.id))
        db.commit()

    return jsonify({
        "success": True,
        "message": "Cookie saved"
    })


# ── Chrome Extension: Cookie Status ───────────────────────────────────────────
@app.route("/cookie_status")
@login_required
def cookie_status():
    """Returns whether the current user has a valid LeetCode cookie stored."""
    with get_db() as db:
        user = db.execute(
            "SELECT lc_session_cookie, cookie_expiry FROM users WHERE id=?",
            (current_user.id,)
        ).fetchone()
    has_cookie = bool(user and user["lc_session_cookie"])
    expired = bool(user and user.get("cookie_expiry", 0))
    return jsonify({
        "connected": has_cookie and not expired,
        "expired": expired
    })


# ── Settings ──────────────────────────────────────────────────────────────────
@app.route("/settings", methods=["GET", "POST"])
@login_required
@verified_required
def settings():
    if request.method == "POST":
        action = request.form.get("action", "profile")
        with get_db() as db:
            if action == "profile":
                cf = sanitize(request.form.get("cf_handle", ""), 64)
                lc = sanitize(request.form.get("lc_handle", ""), 64)
                lc_pw = request.form.get("lc_password", "").strip()[:128]
                lc_cookie = request.form.get("lc_session_cookie", "").strip()[:500]
                lc_csrf = request.form.get("lc_csrf_token", "").strip()[:100]
                ac = sanitize(request.form.get("ac_handle", ""), 64)
                sid = sanitize(request.form.get("sheet_id", ""), 128)
                bio = sanitize(request.form.get("bio", ""), 300)
                pub = 1 if request.form.get("is_public") else 0
                plat = request.form.getlist("platforms")
                if not plat:
                    plat = ["Codeforces", "LeetCode", "AtCoder"]
                valid_plat = [p for p in plat
                              if p in ["Codeforces", "LeetCode", "AtCoder"]]
                db.execute("""
                    UPDATE users SET cf_handle=?,lc_handle=?,lc_password=?,
                    lc_session_cookie=?,lc_csrf_token=?,ac_handle=?,sheet_id=?,bio=?,is_public=?,
                    enabled_platforms=? WHERE id=?
                """, (cf, lc,
                      generate_password_hash(lc_pw) if lc_pw else current_user.lc_password,
                      lc_cookie, lc_csrf,
                      ac, sid, bio, pub,
                      json.dumps(valid_plat), current_user.id))
                flash("Profile settings saved!", "success")
                print("COOKIE:", lc_cookie[:20])
                print("CSRF:", lc_csrf)

            elif action == "password":
                old = request.form.get("old_password", "")
                new = request.form.get("new_password", "")
                conf = request.form.get("confirm_password", "")
                row = db.execute("SELECT password FROM users WHERE id=?",
                                  (current_user.id,)).fetchone()
                if not check_password_hash(row["password"], old):
                    flash("Current password incorrect.", "error")
                elif new != conf:
                    flash("New passwords don't match.", "error")
                elif len(new) < 6:
                    flash("Min 6 characters.", "error")
                else:
                    db.execute("UPDATE users SET password=? WHERE id=?",
                               (generate_password_hash(new), current_user.id))
                    flash("Password changed!", "success")
            db.commit()
        return redirect(url_for("settings"))
    return render_template("settings.html", user=current_user)


# ── LeetCode Connect (browser automation) ─────────────────────────────────────
@app.route("/leetcode/connect", methods=["POST"])
@login_required
def leetcode_connect():
    if webdriver is None or Service is None or ChromeDriverManager is None:
        return jsonify({"success": False, "message": "Browser automation dependencies are not installed."}), 503

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    driver.get("https://leetcode.com/accounts/login/")

    for _ in range(120):
        cookies = driver.get_cookies()
        names = [c["name"] for c in cookies]

        if "LEETCODE_SESSION" in names:
            break

        time.sleep(1)

    if "LEETCODE_SESSION" not in names:
        driver.quit()

        return jsonify({
            "success": False,
            "message": "Login timeout. Please try again."
        })
    lc_session = None
    csrf_token = None

    for cookie in cookies:
        if cookie["name"] == "LEETCODE_SESSION":
            lc_session = cookie["value"]
        elif cookie["name"] == "csrftoken":
            csrf_token = cookie["value"]

    if lc_session and csrf_token:
        with get_db() as db:
            db.execute(
                """
                UPDATE users
                SET lc_session_cookie=?,
                    lc_csrf_token=?
                WHERE id=?
                """,
                (
                    lc_session,
                    csrf_token,
                    current_user.id
                )
            )
            db.commit()

        driver.quit()

        return jsonify({
            "success": True,
            "message": "LeetCode Connected"
        })

    driver.quit()

    return jsonify({
        "success": False,
        "message": "Login Failed"
    })


# ── Sync-time / auto-sync toggle ──────────────────────────────────────────────
@app.route("/set_sync_time", methods=["POST"])
@login_required
def set_sync_time():
    data = request.json or {}
    sync_time = data.get("time", "09:00")

    with get_db() as db:
        db.execute(
            "UPDATE users SET sync_time=? WHERE id=?",
            (sync_time, current_user.id)
        )
        db.commit()

    return jsonify({"success": True, "sync_time": sync_time})


@app.route("/toggle_auto_sync", methods=["POST"])
@login_required
def toggle_auto_sync():
    data = request.json or {}
    enabled = 1 if data.get("enabled") else 0
    with get_db() as db:
        db.execute(
            "UPDATE users SET auto_sync_enabled=? WHERE id=?",
            (enabled, current_user.id)
        )
        db.commit()
    return jsonify({"success": True, "enabled": bool(enabled)})


# ── Feedback ───────────────────────────────────────────────────────────────────
@app.route("/feedback", methods=["POST"])
@login_required
def feedback():
    try:
        data = request.get_json() or {}

        feedback_text = data.get("feedback", "").strip()

        if not feedback_text:
            return jsonify({
                "success": False,
                "message": "Feedback is empty"
            })

        html = f"""
        <h2>New DSA Tracker Feedback</h2>

        <p><b>User:</b> {current_user.username}</p>

        <p><b>Email:</b> {getattr(current_user, 'email', '')}</p>

        <p><b>Feedback:</b></p>

        <p>{feedback_text}</p>
        """

        success = send_email(
            os.getenv("ADMIN_EMAIL"),
            "DSA Tracker Feedback",
            html
        )

        if success:
            return jsonify({
                "success": True,
                "message": "Feedback sent successfully"
            })

        return jsonify({
            "success": False,
            "message": "Unable to send feedback"
        }), 500

    except Exception as e:
        print("FEEDBACK ERROR =", e)

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500