from flask import Blueprint, render_template, redirect, session, jsonify
from app.db import get_db
from app.decorators import login_required
from flask import url_for
from app.db import get_cursor


public_bp = Blueprint("public", __name__)

@public_bp.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("public.dashboard"))  # 🔥 FIX
    return render_template("public/index.html")

def get_dashboard_url(role):
    routes = {
        "student": "student.student_dashboard",
        "company": "company.dashboard",
        "admin": "admin.overview",
    }

    endpoint = routes.get(role, "auth.login")
    return url_for(endpoint)

@public_bp.route("/dashboard")
@login_required
def dashboard():
    role = (session.get("role") or "").strip().lower()  # 🔥 FIX
    return redirect(get_dashboard_url(role))

@public_bp.route("/faq")
def faq():
    return render_template("public/faq.html")

@public_bp.route("/about")
def about():
    return render_template("public/about.html")

@public_bp.route("/post")
@login_required
def post():
    role = (session.get("role") or "").strip().lower()

    if role != "company":
        return redirect(url_for("public.dashboard"))

    return redirect(url_for("company.dashboard"))


@public_bp.route("/discover")
def discover():
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT internships.*, companies.name AS company
                FROM internships
                LEFT JOIN companies ON companies.id = internships.company_id
                WHERE internships.approved = TRUE
            """)
            rows = cur.fetchall()

        return render_template(
            "public/internships.html",
            internships=rows
        )

    except Exception as e:
        print("DISCOVER ERROR:", e)
        return "Internal Server Error", 500

@public_bp.route("/companies")
def companies():
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT * FROM companies
            """)
            rows = cur.fetchall()

        return render_template(
            "public/forcompanies.html",
            companies=rows
        )

    except Exception as e:
        print("COMPANIES ERROR:", e)
        return "Internal Server Error", 500


@public_bp.route("/contact")
def contact():
    return render_template("public/contact.html")

@public_bp.route("/privacy")
def privacy():
    return render_template("public/privacy.html")

@public_bp.route("/terms")
def terms():
    return render_template("public/terms.html")



@public_bp.route("/api/internship/<int:id>/view")
def track_view(id):
    try:
        with get_cursor() as cur:
            # 🔍 CHECK EXISTENCE
            cur.execute("""
                SELECT id FROM analytics WHERE internship_id = %s
            """, (id,))
            row = cur.fetchone()

            if row:
                # 🔄 UPDATE
                cur.execute("""
                    UPDATE analytics
                    SET views = views + 1
                    WHERE internship_id = %s
                """, (id,))
            else:
                # ➕ INSERT
                cur.execute("""
                    INSERT INTO analytics (internship_id, views, applications)
                    VALUES (%s, 1, 0)
                """, (id,))

        return jsonify({"success": True})

    except Exception as e:
        print("TRACK VIEW ERROR:", e)
        return jsonify({"success": False}), 500