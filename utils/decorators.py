"""
utils/decorators.py — auth/authorization decorators used across routes.
Moved verbatim from app.py. `login_required` is just re-exported from
flask_login so routes only need one import line.
"""

from functools import wraps
from datetime import datetime

from flask import flash, redirect, url_for, request
from flask_login import login_required, current_user  # noqa: F401 (re-exported)

from database.db import get_db

__all__ = ["login_required", "admin_required", "verified_required", "log_admin"]


def admin_required(f):
    @wraps(f)
    def wrapped(*a, **kw):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Admin access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*a, **kw)
    return wrapped


def verified_required(f):
    @wraps(f)
    def wrapped(*a, **kw):
        if not current_user.is_verified or current_user.status != "active":
            return redirect(url_for("pending"))
        return f(*a, **kw)
    return wrapped


def log_admin(action, target="", details=""):
    with get_db() as db:
        db.execute("""
            INSERT INTO admin_logs
            (admin_id,action,target_user,details,ip,created_at)
            VALUES (?,?,?,?,?,?)
        """, (current_user.id, action, target, details,
              request.remote_addr, datetime.now().isoformat()))
        db.commit()
