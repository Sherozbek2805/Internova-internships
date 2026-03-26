from math import ceil
from flask import Blueprint, render_template, request, redirect, session, jsonify, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from app.extensions import limiter
from app.db import get_db
from app.decorators import login_required, role_required
import os
from app.db import get_cursor

company_bp = Blueprint("company", __name__, url_prefix="/company")


# =========================
# HELPERS
# =========================
def clean(value):
    return (value or "").strip()


def validate_email(email):
    import re
    return re.match(r"^[^@]+@[^@]+\.[^@]+$", email)

def get_company(conn):
    user_id = session.get("user_id")

    if not user_id:
        return None

    cur = get_cursor(conn)

    cur.execute("""
        SELECT * FROM companies WHERE user_id = %s
    """, (user_id,))
    company = cur.fetchone()

    return company  # returns dict or None


def get_status_counts(conn, company_id):
    cur = get_cursor(conn)  # 🔥 FIX

    cur.execute("""
        SELECT
            COUNT(a.id) AS total_applications,
            COUNT(*) FILTER (WHERE a.status = 'Ko''rib chiqilmoqda') AS reviewing_count,
            COUNT(*) FILTER (WHERE a.status = 'Qisqa ro''yxat') AS shortlisted_count,
            COUNT(*) FILTER (WHERE a.status = 'Saralangan') AS selected_count,
            COUNT(*) FILTER (WHERE a.status = 'Rad etilgan') AS rejected_count
        FROM applications a
        JOIN internships i ON i.id = a.internship_id
        WHERE i.company_id = %s
    """, (company_id,))

    stats = cur.fetchone()

    # ✅ SAFETY (very important)
    return stats or {
        "total_applications": 0,
        "reviewing_count": 0,
        "shortlisted_count": 0,
        "selected_count": 0,
        "rejected_count": 0
    }


def build_candidates_query(company_id, internship_title, status, min_score):
    query = """
        FROM applications
        JOIN internships ON internships.id = applications.internship_id
        JOIN users ON users.id = applications.student_id
        WHERE internships.company_id = %s
    """
    params = [company_id]

    # 🎯 FILTER BY INTERNSHIP
    if internship_title and internship_title != "all":
        query += " AND internships.title = %s"
        params.append(internship_title)

    # 🎯 FILTER BY STATUS
    if status and status != "all":
        query += " AND applications.status = %s"
        params.append(status)

    # 🎯 FILTER BY SCORE (SAFE)
    if min_score is not None:
        query += " AND COALESCE(applications.score, 0) >= %s"
        params.append(min_score)

    return query, params

# =========================
# DASHBOARD
# =========================

@company_bp.route("/dashboard")
@limiter.exempt
@login_required
@role_required("company")
def dashboard():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        # 🏢 GET COMPANY
        company = get_company(conn)
        if not company:
            return "Company not found", 404

        # 📄 INTERNSHIPS
        cur.execute("""
            SELECT * FROM internships
            WHERE company_id = %s
            ORDER BY id DESC
        """, (company["id"],))
        internships = cur.fetchall()

        # 📊 STATS
        stats = get_status_counts(conn, company["id"])

        return render_template(
            "company/dashboard.html",
            company=company,
            internships=internships,
            stats=stats
        )

    finally:
        conn.close()


# =========================
# POST INTERNSHIP PAGE
# =========================

@company_bp.route("/post")
@login_required
@role_required("company")
def post_page():
    conn = get_db()

    try:
        company = get_company(conn)

        if not company:
            return "Company not found", 404

        return render_template("company/post.html", company=company)

    finally:
        conn.close()


@company_bp.route("/internships/create", methods=["POST"])
@login_required
@role_required("company")
def create_internship():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX
        company = get_company(conn)

        # 🚫 AUTH CHECK
        if not company or not company["verified"]:
            return jsonify({"status": "error", "message": "Not allowed"}), 403

        # 📝 VALIDATION (important)
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()

        if not title or not description:
            return jsonify({
                "status": "error",
                "message": "Title and description are required"
            }), 400

        # 📥 INSERT
        cur.execute("""
            INSERT INTO internships (
                company_id, title, description, location,
                duration, deadline, stipend, skills, internship_type
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            company["id"],
            title,
            description,
            request.form.get("location"),
            request.form.get("duration"),
            request.form.get("deadline"),
            request.form.get("stipend"),
            request.form.get("skills"),
            request.form.get("internship_type"),
        ))

        conn.commit()

        return jsonify({
            "status": "success",
            "message": "🚀 Internship created successfully!"
        })

    except Exception as e:
        conn.rollback()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:
        conn.close()

# =========================
# CANDIDATES PAGE
# =========================

@company_bp.route("/candidates")
@limiter.exempt
@login_required
@role_required("company")
def candidates():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX
        company = get_company(conn)

        if not company:
            return "Company not found", 404

        internship = request.args.get("internship") or "all"
        status = request.args.get("status") or "all"
        raw_score = request.args.get("min_score")

        # 🎯 SCORE PARSING
        if raw_score in (None, "", "all"):
            min_score = None
        else:
            try:
                min_score = int(raw_score)
            except ValueError:
                min_score = None

        sort = request.args.get("sort", "default")
        search = request.args.get("search", "")

        params = [company["id"]]

        base_query = """
            FROM applications
            JOIN internships ON internships.id = applications.internship_id
            JOIN users ON users.id = applications.student_id
            WHERE internships.company_id = %s
        """

        # 🔍 SEARCH
        if search:
            base_query += """
                AND (
                    users.name ILIKE %s
                    OR users.email ILIKE %s
                    OR internships.title ILIKE %s
                    OR applications.status ILIKE %s
                    OR applications.evaluation_note ILIKE %s
                )
            """
            params.extend([f"%{search}%"] * 5)

        # 🎯 FILTERS
        if internship != "all":
            base_query += " AND internships.title ILIKE %s"
            params.append(f"%{internship}%")

        if status != "all":
            base_query += " AND applications.status = %s"
            params.append(status)

        if min_score is not None:
            base_query += " AND applications.score >= %s"
            params.append(min_score)

        # 🔃 SORT
        order = "applications.id DESC"
        if sort == "score-desc":
            order = "applications.score DESC"
        elif sort == "score-asc":
            order = "applications.score ASC"

        # 📄 MAIN QUERY
        cur.execute(f"""
            SELECT applications.*, 
                   users.cv_path AS cv_path,
                   users.name AS student_name,
                   users.email AS student_email,
                   internships.title AS internship_title
            {base_query}
            ORDER BY {order}
        """, params)

        applications = cur.fetchall()

        # 📄 INTERNSHIP TITLES
        cur.execute("""
            SELECT title FROM internships WHERE company_id = %s
        """, (company["id"],))
        internships = cur.fetchall()

        data = {
            "applications": applications,  # already dict ✅
            "internships": [i["title"] for i in internships]
        }

        # ⚡ AJAX RESPONSE
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(data)

        return render_template("company/candidates.html")

    finally:
        conn.close()

@company_bp.route("/candidates/stats")
@limiter.exempt
@login_required
@role_required("company")
def candidate_stats():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX
        company = get_company(conn)

        if not company:
            return jsonify({"error": "Company not found"}), 404

        cur.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN applications.status = 'Ko''rib chiqilmoqda' THEN 1 ELSE 0 END) as reviewing,
                SUM(CASE WHEN applications.status = 'Qisqa ro''yxat' THEN 1 ELSE 0 END) as shortlisted,
                SUM(CASE WHEN applications.status = 'Saralangan' THEN 1 ELSE 0 END) as selected
            FROM applications
            JOIN internships ON internships.id = applications.internship_id
            WHERE internships.company_id = %s
        """, (company["id"],))
        
        stats = cur.fetchone() or {}

        return jsonify({
            "total": stats.get("total", 0) or 0,
            "reviewing": stats.get("reviewing", 0) or 0,
            "shortlisted": stats.get("shortlisted", 0) or 0,
            "selected": stats.get("selected", 0) or 0
        })

    finally:
        conn.close()

@company_bp.route("/applications/update", methods=["POST"])
@login_required
@role_required("company")
def update_application():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX
        company = get_company(conn)

        # 🚫 COMPANY CHECK
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404

        app_id = request.form.get("id")
        score = request.form.get("score")
        status = request.form.get("status")
        note = request.form.get("note")

        # ✅ VALIDATION
        if not app_id:
            return jsonify({"status": "error", "message": "Missing application ID"}), 400

        try:
            app_id = int(app_id)
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid application ID"}), 400

        try:
            score = int(score or 0)
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid score"}), 400

        if status not in ["Yangi", "Ko'rib chiqilmoqda", "Qisqa ro'yxat", "Saralangan"]:
            return jsonify({"status": "error", "message": "Invalid status"}), 400

        # 🔄 UPDATE (STRICTLY SCOPED)
        cur.execute("""
            UPDATE applications
            SET score = %s,
                status = %s,
                evaluation_note = %s
            WHERE id = %s
              AND internship_id IN (
                  SELECT id FROM internships WHERE company_id = %s
              )
            RETURNING id
        """, (score, status, note, app_id, company["id"]))

        updated = cur.fetchone()

        if not updated:
            return jsonify({
                "status": "error",
                "message": "Application not found or not allowed"
            }), 404

        conn.commit()

        return jsonify({
            "status": "success",
            "message": "Updated successfully"
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        conn.close()
    

@company_bp.route("/applications/<int:id>")
@login_required
@role_required("company")
def get_application(id):
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX
        company = get_company(conn)

        if not company:
            return jsonify({"error": "Company not found"}), 404

        # 🔐 SECURE QUERY (scoped to company)
        cur.execute("""
            SELECT 
                users.name,
                users.email,
                users.school,
                users.skills,
                users.cv_path
            FROM applications
            JOIN users ON users.id = applications.student_id
            JOIN internships ON internships.id = applications.internship_id
            WHERE applications.id = %s
              AND internships.company_id = %s
        """, (id, company["id"]))
        
        app = cur.fetchone()

        if not app:
            return jsonify({"error": "Not found"}), 404

        filename = os.path.basename(app["cv_path"]) if app["cv_path"] else None

        return jsonify({
            "name": app["name"],
            "email": app["email"],
            "school": app["school"],
            "skills": app["skills"],
            "cv_url": f"/static/uploads/cv/{filename}" if filename else None
        })

    finally:
        conn.close()
# =========================
# SETTINGS PAGE
# =========================

@company_bp.route("/settings")
@login_required
@role_required("company")
def settings_page():
    conn = get_db()

    try:
        company = get_company(conn)

        if not company:
            return "Company not found", 404

        return render_template(
            "company/settings.html",
            company=company
        )

    finally:
        conn.close()

@company_bp.route("/settings/update", methods=["POST"])
@login_required
@role_required("company")
def update_settings():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX
        company = get_company(conn)

        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404

        data = request.form

        name = clean(data.get("name"))
        email = clean(data.get("email"))
        phone1 = clean(data.get("phone1"))
        phone2 = clean(data.get("phone2"))
        website = clean(data.get("website"))
        description = clean(data.get("description"))
        logo_url = clean(data.get("logo_url"))

        # ✅ VALIDATION
        errors = {}

        if not name:
            errors["name"] = "Name is required"
        elif len(name) < 2:
            errors["name"] = "Name too short"

        if not email or not validate_email(email):
            errors["email"] = "Valid email required"

        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        # 🔍 DUPLICATE EMAIL
        cur.execute("""
            SELECT id FROM companies 
            WHERE LOWER(email) = LOWER(%s) AND id != %s
        """, (email, company["id"]))
        existing = cur.fetchone()

        if existing:
            return jsonify({
                "status": "error",
                "errors": {"email": "Email already in use"}
            }), 400

        # ✏️ UPDATE
        cur.execute("""
            UPDATE companies SET
                name = %s,
                email = %s,
                phone1 = %s,
                phone2 = %s,
                website = %s,
                description = %s,
                logo_url = %s
            WHERE id = %s
            RETURNING id
        """, (name, email, phone1, phone2, website, description, logo_url, company["id"]))

        updated = cur.fetchone()

        if not updated:
            return jsonify({
                "status": "error",
                "message": "Update failed"
            }), 500

        conn.commit()

        return jsonify({
            "status": "success",
            "message": "Settings updated successfully",
            "company": {
                "name": name,
                "email": email,
                "phone1": phone1,
                "phone2": phone2,
                "website": website,
                "description": description,
                "logo_url": logo_url
            }
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        conn.close()

# =========================
# CHANGE PASSWORD
# =========================
@company_bp.route("/change-password", methods=["POST"])
@login_required
@role_required("company")
def change_password():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        data = request.form

        current_password = (data.get("current_password") or "").strip()
        new_password = (data.get("new_password") or "").strip()
        confirm_password = (data.get("confirm_password") or "").strip()

        # ✅ VALIDATION
        if not current_password or not new_password or not confirm_password:
            return jsonify({"status": "error", "message": "All fields required"}), 400

        if new_password != confirm_password:
            return jsonify({"status": "error", "message": "Passwords do not match"}), 400

        if len(new_password) < 8:
            return jsonify({"status": "error", "message": "Password must be at least 8 characters"}), 400

        # 🔍 FETCH USER
        cur.execute("""
            SELECT password FROM users WHERE id = %s
        """, (user_id,))
        user = cur.fetchone()

        if not user:
            return jsonify({"status": "error", "message": "User not found"}), 404

        # 🔐 CHECK PASSWORD
        if not check_password_hash(user["password"], current_password):
            return jsonify({"status": "error", "message": "Wrong current password"}), 400

        if check_password_hash(user["password"], new_password):
            return jsonify({"status": "error", "message": "New password must be different"}), 400

        # 🔐 UPDATE PASSWORD
        hashed_password = generate_password_hash(new_password)

        cur.execute("""
            UPDATE users SET password = %s WHERE id = %s
        """, (hashed_password, user_id))

        conn.commit()

        return jsonify({
            "status": "success",
            "message": "Password updated successfully"
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        conn.close()