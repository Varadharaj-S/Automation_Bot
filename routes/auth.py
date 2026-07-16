"""
routes/auth.py — index redirect, login, signup, email verification,
logout, and the separate admin login. Moved verbatim from app.py.
"""

import re
import time
import secrets
import threading
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import app
from database.db import get_db, IntegrityError
from utils.security import sanitize, rate_limit
from services.auth_service import User
from services.email_service import send_verification_email


# ── Index ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin_dashboard"))
        if not current_user.is_verified or current_user.status != "active":
            return redirect(url_for("pending"))
        return redirect(url_for("dashboard"))  # correct now
    return redirect(url_for("login"))


# ── User Auth ─────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
@rate_limit(max_calls=10, window=60)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = sanitize(request.form.get("username", ""))
        password = request.form.get("password", "")
        ip, ua = request.remote_addr, request.user_agent.string[:200]

        with get_db() as db:
            row = db.execute(
                "SELECT * FROM users WHERE username=? AND is_admin=0", (username,)
            ).fetchone()
            ok = bool(row and check_password_hash(row["password"], password))
            db.execute("""
                INSERT INTO login_history
                (user_id,ip,user_agent,success,created_at)
                VALUES (?,?,?,?,?)
            """, (row["id"] if row else None, ip, ua,
                  1 if ok else 0, datetime.now().isoformat()))
            if ok:
                db.execute("UPDATE users SET last_login=? WHERE id=?",
                           (datetime.now().strftime("%Y-%m-%d %H:%M"), row["id"]))
            db.commit()

        if ok:
            user = User(row)
            if row["status"] != "active":
                flash("Your account is pending admin verification.", "warning")
                return redirect(url_for("pending"))
            session.clear()

            login_user(
                user,
                remember=False,
                fresh=True
            )

            session.permanent = True
            session["_last_active"] = time.time()
            flash(f"Welcome back, {username}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
@rate_limit(max_calls=5, window=300)
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = sanitize(request.form.get("username", ""), 32)
        email = sanitize(request.form.get("email", ""), 120)
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        full_name = sanitize(request.form.get("full_name", ""), 120)
        reg_no = sanitize(request.form.get("reg_no", ""), 40)
        roll_no = sanitize(request.form.get("roll_no", ""), 40)
        branch = sanitize(request.form.get("branch", ""), 40)

        if not username or len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
        elif not re.match(r'^[a-zA-Z0-9_]+$', username):
            flash("Username: letters, numbers, _ only.", "error")
        elif not full_name:
            flash("Full name is required.", "error")
        elif not reg_no:
            flash("Register number is required.", "error")
        elif not branch:
            flash("Branch is required.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        elif len(password) < 6:
            flash("Password min. 6 characters.", "error")
        else:
            try:
                with get_db() as db:
                    existing_reg = db.execute(
                        "SELECT 1 FROM users WHERE reg_no=? AND reg_no != ''", (reg_no,)
                    ).fetchone()
                    if existing_reg:
                        flash("That register number is already registered.", "error")
                        return render_template("signup.html")

                    db.execute("""
                        INSERT INTO users
                        (username,email,password,is_verified,status,
                         enabled_platforms,created_at,full_name,reg_no,roll_no,branch)
                        VALUES (?,?,?,0,'pending',?,?,?,?,?,?)
                    """, (username, email, generate_password_hash(password),
                          '["Codeforces","LeetCode","AtCoder"]',
                          datetime.now().isoformat(),
                          full_name, reg_no, roll_no, branch))
                    db.commit()
                    user_row = db.execute(
                        "SELECT id FROM users WHERE username=?", (username,)
                    ).fetchone()
                    uid = user_row["id"]
                    token = secrets.token_urlsafe(32)
                    db.execute("""
                        INSERT INTO email_tokens (user_id, token, created_at)
                        VALUES (?,?,?)
                    """, (uid, token, datetime.now().isoformat()))
                    db.commit()

                threading.Thread(
                    target=send_verification_email,
                    args=(email, username, token),
                    daemon=True
                ).start()

                flash("Account created! Please check your email to verify your address, then wait for admin approval.", "success")
                return redirect(url_for("pending"))
            except IntegrityError:
                flash("Username already taken.", "error")
    return render_template("signup.html")


def _create_sheet_bg(username, email):
    """Background: create Google Sheet and save ID to user record.
    NOTE: preserved from the original app.py, where this was also defined
    but never actually called from anywhere (signup() only threads
    send_verification_email, not this). Kept as-is rather than silently
    dropped or wired in, since either change would be a behavior change,
    not a refactor."""
    from services.sync_engine import create_user_sheet
    sheet_id, msg = create_user_sheet(email, username)
    if sheet_id:
        with get_db() as db:
            db.execute("UPDATE users SET sheet_id=? WHERE username=?",
                       (sheet_id, username))
            db.commit()
        print(f"[Sheets] Created sheet for {username}: {sheet_id}")
    else:
        print(f"[Sheets] Failed for {username}: {msg}")


@app.route("/verify_email/<token>")
def verify_email(token):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM email_tokens WHERE token=? AND used=0", (token,)
        ).fetchone()
        if not row:
            flash("Invalid or expired verification link.", "error")
            return redirect(url_for("login"))

        # Check token not older than 24h
        created = datetime.fromisoformat(row["created_at"])
        if datetime.now() - created > timedelta(hours=24):
            flash("Verification link has expired. Please contact admin.", "error")
            return redirect(url_for("login"))

        uid = row["user_id"]
        db.execute("UPDATE email_tokens SET used=1 WHERE token=?", (token,))
        db.execute("UPDATE users SET is_verified=1 WHERE id=? AND status='pending'", (uid,))
        # Note: status stays 'pending' until admin approves — is_verified=1 just means email confirmed
        db.commit()

        user_row = db.execute("SELECT username FROM users WHERE id=%s", (uid,)).fetchone()
        username = user_row["username"] if user_row else "User"

    flash(f"✅ Email verified! Hi {username} — your account is now pending admin approval.", "success")
    return redirect(url_for("pending"))


@app.route("/pending")
def pending():
    return render_template("pending.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()

    session.clear()

    resp = redirect(url_for("login"))

    resp.delete_cookie("remember_token")
    resp.delete_cookie(app.config["SESSION_COOKIE_NAME"])

    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"

    flash("Logged out successfully.", "success")

    return resp


# ── Separate Admin Login ───────────────────────────────────────────────────────
@app.route("/admin/login", methods=["GET", "POST"])
@rate_limit(max_calls=5, window=60)
def admin_login():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        username = sanitize(request.form.get("username", ""))
        password = request.form.get("password", "")
        ip, ua = request.remote_addr, request.user_agent.string[:200]
        with get_db() as db:
            row = db.execute(
                "SELECT * FROM users WHERE username=? AND is_admin=1", (username,)
            ).fetchone()
            ok = bool(row and check_password_hash(row["password"], password))
            db.execute("""
                INSERT INTO login_history (user_id,ip,user_agent,success,created_at)
                VALUES (?,?,?,?,?)
            """, (row["id"] if row else None, ip, ua,
                  1 if ok else 0, datetime.now().isoformat()))
            if ok:
                db.execute("UPDATE users SET last_login=? WHERE id=?",
                           (datetime.now().strftime("%Y-%m-%d %H:%M"), row["id"]))
            db.commit()
        if ok:
            session.clear()

            login_user(
                User(row),
                remember=False,
                fresh=True
            )

            session.permanent = True
            session["_last_active"] = time.time()
            flash(f"Admin login: {username}", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin credentials.", "error")
    return render_template("admin_login.html")
