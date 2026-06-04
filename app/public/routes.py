import re
from flask import Blueprint, abort, render_template, redirect, session, jsonify, request, flash
from app.db import get_db
from app.decorators import login_required, role_required
from flask import url_for
from app.db import get_cursor


public_bp = Blueprint("public", __name__)

@public_bp.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("public.dashboard"))  # 🔥 FIX
    #return render_template("public/waitlist.html")
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



@public_bp.route("/api/internship/<int:id>/view", methods=["GET", "POST"])
def track_view(id):
    """Increment view count for an internship. Uses internship_stats table."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO internship_stats (internship_id, views, applications)
                VALUES (%s, 1, 0)
                ON CONFLICT (internship_id)
                DO UPDATE SET views = internship_stats.views + 1
            """, (id,))
        return jsonify({"success": True})
    except Exception:
        import logging
        logging.getLogger(__name__).exception("track_view failed")
        return jsonify({"success": False}), 500

@public_bp.route("/directory/companies")
def company_directory():

    try:

        with get_cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    name,
                    description,
                    website,
                    logo_url,
                    industry
                FROM companies
                WHERE verified = TRUE
                ORDER BY name
            """)

            companies = cur.fetchall()

        return render_template(
            "public/company_directory.html",
            companies=companies
        )

    except Exception as e:

        print("COMPANY DIRECTORY ERROR:", e)

        return "Internal Server Error", 500
    
@public_bp.route("/companies/<int:id>")
def company_portal(id):

    try:

        with get_cursor() as cur:

            # COMPANY
            cur.execute("""
                SELECT *
                FROM companies
                WHERE id = %s
            """, (id,))

            company = cur.fetchone()

            if not company:
                abort(404)

            # INTERNSHIPS
            cur.execute("""
                SELECT *
                FROM internships
                WHERE company_id = %s
                ORDER BY created_at DESC
            """, (id,))

            internships = cur.fetchall()

        return render_template(
            "public/company_portal.html",
            company=company,
            internships=internships
        )

    except Exception as e:

        print("COMPANY PORTAL ERROR:", e)

        return "Internal Server Error", 500

    
@public_bp.route("/waitlist", methods=["GET"])
def waitlist_page():
    """GET-only: serve the waitlist page. POST is handled by auth_bp.waitlist."""
    return render_template("public/waitlist.html")


@public_bp.route("/companies/<int:id>/access", methods=["POST"])
def company_access(id):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json

    data = request.get_json(silent=True) or request.form
    access_code = (data.get("access_code") or "").strip()

    if not access_code:
        if is_ajax:
            return jsonify({"success": False, "message": "Access code required."}), 400
        flash("Access code required.", "error")
        return redirect(f"/companies/{id}")

    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT id FROM external_company_access
                WHERE company_id = %s
                  AND access_code = %s
                  AND is_active = TRUE
                  AND (expires_at IS NULL OR expires_at > NOW())
            """, (id, access_code))
            access = cur.fetchone()

        if not access:
            if is_ajax:
                return jsonify({"success": False, "message": "Invalid or expired access code."}), 403
            flash("Invalid access code.", "error")
            return redirect(f"/companies/{id}")

        session["external_company_access"] = True
        session["external_company_id"] = id

        dashboard_url = url_for("company.dashboard")
        if is_ajax:
            return jsonify({"success": True, "redirect": dashboard_url})
        return redirect(dashboard_url)

    except Exception:
        import logging
        logging.getLogger(__name__).exception("company_access failed")
        if is_ajax:
            return jsonify({"success": False, "message": "Server error."}), 500
        return "Internal Server Error", 500