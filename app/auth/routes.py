import re
from flask import (
    Blueprint, render_template, request, jsonify,
    redirect, session, url_for, current_app, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.db import get_db
from app.db import get_cursor
from app.extensions import oauth, limiter, csrf
from app.public.routes import get_dashboard_url

auth_bp = Blueprint("auth", __name__)

google = None

EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
PASSWORD_PATTERN = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$"


# -------------------- OAUTH --------------------
def init_oauth(app):
    global google
    google = oauth.register(
        name="google",
        client_id=app.config.get("GOOGLE_CLIENT_ID"),
        client_secret=app.config.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


# -------------------- TOKEN --------------------
def get_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generate_email_verification_token(data):
    return get_serializer().dumps(data, salt="email-verification")


def verify_email_token(token, max_age):
    return get_serializer().loads(token, salt="email-verification", max_age=max_age)


# -------------------- HELPERS --------------------
def normalize_email(email):
    return (email or "").strip().lower()


def is_valid_email(email):
    return re.match(EMAIL_PATTERN, email) is not None


def is_valid_password(password):
    return re.match(PASSWORD_PATTERN, password) is not None


def wants_json_response():
    return request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest"


def login_user(user):
    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    session.permanent = True
    session.modified = True


def redirect_by_role(role):
    if role == "student":
        return redirect(url_for("student.student_dashboard"))
    if role == "company":
        return redirect(url_for("company.dashboard"))
    if role == "admin":
        return redirect(url_for("admin.overview"))

    session.clear()
    return jsonify({
        "success": False,
        "message": "Invalid user role."
    }), 400

# -------------------- LOGIN --------------------
# -------------------- LOGIN --------------------
@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if request.method == "GET":
        return render_template("public/login.html")

    data = request.get_json(silent=True) or request.form

    email = normalize_email(data.get("email"))
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "").strip().lower()

    # -------------------- VALIDATION --------------------
    if not email or not password or not role:
        return jsonify({
            "success": False,
            "message": "Email, password, and role are required."
        }), 400

    conn = get_db()
    try:
        cur = get_cursor(conn)

        cur.execute(
            "SELECT * FROM users WHERE LOWER(email)=LOWER(%s)",
            (email,)
        )
        user = cur.fetchone()

    except Exception:
        current_app.logger.exception("Login query failed")
        return jsonify({
            "success": False,
            "message": "Internal server error."
        }), 500

    finally:
        conn.close()

    # -------------------- VALIDATION --------------------
    if not user or user["role"] != role:
        return jsonify({
            "success": False,
            "message": "Invalid email, password, or role."
        }), 401

    if user["banned"]:
        return jsonify({
            "success": False,
            "message": "Your account has been blocked."
        }), 403

    # ❌ REMOVED EMAIL VERIFICATION CHECK

    # 🔐 GOOGLE ACCOUNT CHECK
    if not user["password"]:
        return jsonify({
            "success": False,
            "message": "Use Google login for this account."
        }), 400

    # 🔐 PASSWORD CHECK
    if not check_password_hash(user["password"], password):
        return jsonify({
            "success": False,
            "message": "Invalid email, password, or role."
        }), 401

    # ✅ LOGIN SESSION
    login_user(user)

    return jsonify({
        "success": True,
        "redirect": get_dashboard_url(role)
    }), 200

# -------------------- SIGNUP --------------------
# -------------------- SIGNUP --------------------
@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def signup():
    if request.method == "GET":
        return render_template("public/signup.html")

    data = request.get_json(silent=True) or request.form

    name = (data.get("name") or "").strip()
    email = normalize_email(data.get("email"))
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "").strip().lower()
    school = (data.get("school") or "").strip()
    skills = (data.get("skills") or "").strip()
    phone1 = (data.get("phone1") or "").strip()
    phone2 = (data.get("phone2") or "").strip()
    address = (data.get("address") or "").strip()
    industry = (data.get("industry") or "").strip()

    # -------------------- VALIDATION --------------------
    if not name or not email or not password or not role:
        return jsonify({
            "success": False,
            "message": "Missing required fields."
        }), 400

    if role not in {"student", "company"}:
        return jsonify({
            "success": False,
            "message": "Invalid role."
        }), 400

    if not is_valid_email(email):
        return jsonify({
            "success": False,
            "message": "Invalid email format."
        }), 400

    if not is_valid_password(password):
        return jsonify({
            "success": False,
            "message": "Weak password."
        }), 400

    # 🔐 HASH PASSWORD
    hashed_password = generate_password_hash(password)

    # -------------------- DATABASE --------------------
    conn = get_db()
    try:
        cur = get_cursor(conn)

        # 🔍 CHECK IF EMAIL EXISTS
        cur.execute(
            "SELECT id FROM users WHERE LOWER(email)=LOWER(%s)",
            (email,)
        )
        if cur.fetchone():
            return jsonify({
                "success": False,
                "message": "Email already registered."
            }), 400

        # 👤 INSERT USER
        cur.execute("""
            INSERT INTO users (name, email, password, role, school, skills, verified)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id
        """, (
            name,
            email,
            hashed_password,
            role,
            school,
            skills
        ))

        user_id = cur.fetchone()["id"]

        # 🏢 IF COMPANY → CREATE COMPANY PROFILE
        if role == "company":
            cur.execute("""
                INSERT INTO companies (name, user_id, phone1, phone2, address, industry)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                name,
                user_id,
                phone1,
                phone2,
                address,
                industry
            ))

        conn.commit()

    except Exception:
        conn.rollback()
        current_app.logger.exception("Signup failed")
        return jsonify({
            "success": False,
            "message": "Internal server error."
        }), 500

    finally:
        conn.close()

    return jsonify({
        "success": True,
        "message": "Account created successfully."
    }), 200

# -------------------- CHECK EMAIL --------------------
@auth_bp.route("/check-email", methods=["POST"])
@csrf.exempt
def check_email():
    data = request.get_json(silent=True) or {}

    email = normalize_email(data.get("email"))

    # 🔐 VALIDATION
    if not email:
        return jsonify({
            "available": False,
            "message": "Email required"
        }), 400

    if not is_valid_email(email):
        return jsonify({
            "available": False,
            "message": "Invalid email format"
        }), 400

    conn = get_db()
    try:
        cur = get_cursor(conn)

        cur.execute(
            "SELECT id FROM users WHERE LOWER(email)=LOWER(%s)",
            (email,)
        )
        existing = cur.fetchone()

    except Exception:
        current_app.logger.exception("Check email failed")
        return jsonify({
            "available": False,
            "message": "Internal server error"
        }), 500

    finally:
        conn.close()

    if existing:
        return jsonify({
            "available": False,
            "message": "Email already registered"
        }), 200

    return jsonify({
        "available": True
    }), 200

@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("public.index"))

# -------------------- GOOGLE LOGIN --------------------
@auth_bp.route("/login/google")
@limiter.limit("10 per minute")
def google_login():
    if google is None:
        return jsonify({"success": False, "message": "OAuth not configured"}), 500

    redirect_uri = url_for("auth.google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@auth_bp.route("/google/callback")
def google_callback():
    if google is None:
        return jsonify({"success": False, "message": "OAuth not configured"}), 500

    try:
        google.authorize_access_token()
        resp = google.get("https://www.googleapis.com/oauth2/v2/userinfo")
        user_data = resp.json()

        email = normalize_email(user_data.get("email"))
        name = (user_data.get("name") or "Google User").strip()

        if not email:
            return jsonify({
                "success": False,
                "message": "Google account has no email."
            }), 400

        conn = get_db()
        try:
            cur = get_cursor(conn)

            # 🔍 CHECK USER
            cur.execute(
                "SELECT * FROM users WHERE LOWER(email)=LOWER(%s)",
                (email,)
            )
            user = cur.fetchone()

            # 👤 CREATE USER IF NOT EXISTS
            if not user:
                cur.execute("""
                    INSERT INTO users (name, email, password, role, verified)
                    VALUES (%s, %s, %s, %s, TRUE)
                    RETURNING id
                """, (name, email, "", "student"))

                user_id = cur.fetchone()["id"]
                conn.commit()

                # fetch created user
                cur.execute(
                    "SELECT * FROM users WHERE id=%s",
                    (user_id,)
                )
                user = cur.fetchone()

        except Exception:
            conn.rollback()
            current_app.logger.exception("Google DB operation failed")
            return jsonify({
                "success": False,
                "message": "Database error."
            }), 500

        finally:
            conn.close()

        # 🚫 BLOCKED USER
        if user["banned"]:
            return jsonify({
                "success": False,
                "message": "Account blocked."
            }), 403

        # ✅ LOGIN
        login_user(user)
        return redirect_by_role(user["role"])

    except Exception:
        current_app.logger.exception("Google login failed")
        return jsonify({
            "success": False,
            "message": "Google login failed."
        }), 500


# CSRF exemption for OAuth callback
csrf.exempt(google_callback)