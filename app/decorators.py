from functools import wraps
from flask import session, redirect, url_for, flash, abort
from app.db import get_cursor


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user_id = session.get("user_id")

        # ❌ No session
        if not user_id:
            flash("Please log in first.", "warning")
            return redirect(url_for("auth.login"))

        # 🔍 Check DB (VERY IMPORTANT)
        with get_cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id=%s", (user_id,))
            user = cur.fetchone()

        # ❌ User deleted or invalid
        if not user:
            session.clear()  # 🔥 KEY FIX
            flash("Session expired. Please log in again.", "warning")
            return redirect(url_for("auth.login"))

        return view(*args, **kwargs)

    return wrapped_view


def role_required(required_role):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not session.get("user_id"):
                flash("Please log in first.", "warning")
                return redirect(url_for("auth.login"))

            user_role = (session.get("role") or "").strip().lower()

            if user_role != required_role:
                abort(403)

            return view(*args, **kwargs)

        return wrapped_view
    return decorator


def admin_required(view):
    return role_required("admin")(view)


def company_required(view):
    return role_required("company")(view)


def student_required(view):
    return role_required("student")(view)