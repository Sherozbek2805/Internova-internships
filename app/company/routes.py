from math import ceil
from flask import Blueprint, render_template, request, redirect, session, jsonify, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from app.extensions import limiter
from app.db import get_db
from app.decorators import login_required, role_required
import os
from app.db import get_cursor
import json

company_bp = Blueprint("company", __name__, url_prefix="/company")


# =========================
# HELPERS
# =========================
def clean(value):
    return (value or "").strip()


def validate_email(email):
    import re
    return re.match(r"^[^@]+@[^@]+\.[^@]+$", email)

def get_company():
    user_id = session.get("user_id")

    if not user_id:
        return None

    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM companies WHERE user_id = %s
        """, (user_id,))
        company = cur.fetchone()

    return company  # dict or None


def get_status_counts(company_id):
    with get_cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(a.id) AS total_applications,
                COUNT(*) FILTER (WHERE a.status = 'reviewing') AS reviewing_count,
                COUNT(*) FILTER (WHERE a.status = 'shortlisted') AS shortlisted_count,
                COUNT(*) FILTER (WHERE a.status = 'accepted') AS selected_count,
                COUNT(*) FILTER (WHERE a.status = 'rejected') AS rejected_count
            FROM applications a
            WHERE a.company_id = %s
        """, (company_id,))

        stats = cur.fetchone()

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
        JOIN students ON students.id = applications.student_id
        JOIN users ON users.id = students.user_id
        WHERE internships.company_id = %s
    """
    params = [company_id]

    # 🎯 FILTER BY INTERNSHIP
    if internship_title and internship_title != "all":
        query += " AND internships.title = %s"
        params.append(internship_title)

    # 🎯 FILTER BY STATUS (DB-safe)
    if status and status != "all":
        query += " AND applications.status = %s"
        params.append(status)

    # 🎯 FILTER BY SCORE
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
    # 🏢 GET COMPANY
    company = get_company()
    if not company:
        return "Company not found", 404

    # 📄 INTERNSHIPS
    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM internships
            WHERE company_id = %s
            ORDER BY id DESC
        """, (company["id"],))
        internships = cur.fetchall()

    # 📊 STATS
    stats = get_status_counts(company["id"])

    return render_template(
        "company/dashboard.html",
        company=company,
        internships=internships,
        stats=stats
    )


# =========================
# POST INTERNSHIP PAGE
# =========================

@company_bp.route("/post")
@login_required
@role_required("company")
def post_page():
    company = get_company()

    if not company:
        return "Company not found", 404

    return render_template("company/post.html", company=company)


@company_bp.route("/internships/create", methods=["POST"])
@login_required
@role_required("company")
def create_internship():
    company = get_company()

    # 🚫 AUTH CHECK
    if not company or not company["verified"]:
        return jsonify({"status": "error", "message": "Not allowed"}), 403

    # 📝 VALIDATION
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    skills_input = (request.form.get("skills") or "").strip()

    if not title or not description:
        return jsonify({
            "status": "error",
            "message": "Title and description are required"
        }), 400

    try:
        raw_stipend = request.form.get("stipend") or "0"

        # remove commas and spaces
        clean_stipend = raw_stipend.replace(",", "").strip()

        try:
            stipend = int(clean_stipend)
        except ValueError:
            stipend = 0
        with get_cursor() as cur:
            # 📥 INSERT INTERNSHIP
            cur.execute("""
                INSERT INTO internships (
                    company_id, title, description, location,
                    duration, deadline, stipend, type
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                company["id"],
                title,
                description,
                request.form.get("location"),
                request.form.get("duration"),
                request.form.get("deadline"),
                stipend,
                request.form.get("internship_type"),
            ))

            internship_id = cur.fetchone()["id"]

            # 🧠 HANDLE SKILLS (ADVANCED 🔥)
            if skills_input:
                skills = [s.strip().lower() for s in skills_input.split(",") if s.strip()]

                for skill in skills:
                    # 1️⃣ Ensure skill exists
                    cur.execute("""
                        INSERT INTO skills (name)
                        VALUES (%s)
                        ON CONFLICT (name) DO NOTHING
                        RETURNING id
                    """, (skill,))
                    
                    result = cur.fetchone()

                    if result:
                        skill_id = result["id"]
                    else:
                        # already exists → fetch id
                        cur.execute("SELECT id FROM skills WHERE name = %s", (skill,))
                        skill_id = cur.fetchone()["id"]

                    # 2️⃣ Link skill to internship
                    cur.execute("""
                        INSERT INTO internship_skills (internship_id, skill_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                    """, (internship_id, skill_id))

        return jsonify({
            "status": "success",
            "message": "🚀 Internship created successfully!"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# =========================
# CANDIDATES PAGE
# =========================

@company_bp.route("/candidates")
@limiter.exempt
@login_required
@role_required("company")
def candidates():
    company = get_company()

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
        JOIN students ON students.id = applications.student_id
        JOIN users ON users.id = students.user_id
        WHERE applications.company_id = %s
    """

    # 🔍 SEARCH
    if search:
        base_query += """
            AND (
                users.name ILIKE %s
                OR users.email ILIKE %s
                OR internships.title ILIKE %s
                OR applications.status::text ILIKE %s
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

    with get_cursor() as cur:
        # 📄 MAIN QUERY
        cur.execute(f"""
            SELECT applications.*, 
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
        "applications": applications,
        "internships": [i["title"] for i in internships]
    }

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(data)

    return render_template("company/candidates.html")

@company_bp.route("/applications/update", methods=["POST"])
@login_required
@role_required("company")
def update_application():
    company = get_company()

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

    # 🔁 STATUS MAPPING (IMPORTANT 🔥)
    status_map = {
        "Yangi": "new",
        "Ko'rib chiqilmoqda": "reviewing",
        "Qisqa ro'yxat": "shortlisted",
        "Saralangan": "accepted",
        "Rad etilgan": "rejected"
    }

    if status not in status_map:
        return jsonify({"status": "error", "message": "Invalid status"}), 400

    db_status = status_map[status]

    try:
        with get_cursor() as cur:
            cur.execute("""
                UPDATE applications
                SET score = %s,
                    status = %s,
                    evaluation_note = %s
                WHERE id = %s
                  AND company_id = %s
                RETURNING id
            """, (score, db_status, note, app_id, company["id"]))

            updated = cur.fetchone()

        if not updated:
            return jsonify({
                "status": "error",
                "message": "Application not found or not allowed"
            }), 404

        return jsonify({
            "status": "success",
            "message": "Updated successfully"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    

@company_bp.route("/applications/<int:id>")
@login_required
@role_required("company")
def get_application(id):
    company = get_company()

    if not company:
        return jsonify({"error": "Company not found"}), 404

    try:
        with get_cursor() as cur:

            # 🔥 MAIN PROFILE
            cur.execute("""
                SELECT 
                    users.name,
                    users.email,
                    students.school,
                    students.grade,
                    students.program,
                    students.gpa,
                    students.bio,
                    students.location,
                    students.phone,
                    students.telegram,
                    students.linkedin,
                    students.github,
                    applications.motivation,
                    applications.score,
                    applications.evaluation_note,
                    user_files.file_url AS cv_url
                FROM applications
                JOIN students ON students.id = applications.student_id
                JOIN users ON users.id = students.user_id
                LEFT JOIN user_files 
                    ON user_files.user_id = users.id 
                    AND user_files.file_type = 'cv'
                WHERE applications.id = %s
                  AND applications.company_id = %s
            """, (id, company["id"]))

            profile = cur.fetchone()

            if not profile:
                return jsonify({"error": "Not found"}), 404

            # 🔥 SKILLS
            cur.execute("""
                SELECT skills.name
                FROM student_skills
                JOIN skills ON skills.id = student_skills.skill_id
                WHERE student_skills.student_id = (
                    SELECT student_id FROM applications WHERE id = %s
                )
            """, (id,))
            skills = [s["name"] for s in cur.fetchall()]

            # 🔥 EXPERIENCES
            cur.execute("""
                SELECT title, organization, role, description, is_current, grade_levels
                FROM experiences
                WHERE student_id = (
                    SELECT student_id FROM applications WHERE id = %s
                )
                ORDER BY created_at DESC
            """, (id,))
            experiences = cur.fetchall()

            for exp in experiences:
                if isinstance(exp["grade_levels"], str):
                    try:
                        exp["grade_levels"] = json.loads(exp["grade_levels"])
                    except:
                        exp["grade_levels"] = {}

        return jsonify({
            "profile": profile,
            "skills": skills,
            "experiences": experiences
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# SETTINGS PAGE
# =========================

@company_bp.route("/settings")
@login_required
@role_required("company")
def settings_page():
    company = get_company()

    if not company:
        return "Company not found", 404

    return render_template(
        "company/settings.html",
        company=company
    )

@company_bp.route("/settings/update", methods=["POST"])
@login_required
@role_required("company")
def update_settings():
    company = get_company()

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

    try:
        with get_cursor() as cur:
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
            """, (
                name, email, phone1, phone2,
                website, description, logo_url,
                company["id"]
            ))

            updated = cur.fetchone()

        if not updated:
            return jsonify({
                "status": "error",
                "message": "Update failed"
            }), 500

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
        return jsonify({"status": "error", "message": str(e)}), 500

# =========================
# CHANGE PASSWORD
# =========================
@company_bp.route("/change-password", methods=["POST"])
@login_required
@role_required("company")
def change_password():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.form

    current_password = (data.get("current_password") or "").strip()
    new_password = (data.get("new_password") or "").strip()
    confirm_password = (data.get("confirm_password") or "").strip()

    # ✅ BASIC VALIDATION
    if not new_password or not confirm_password:
        return jsonify({"status": "error", "message": "All fields required"}), 400

    if new_password != confirm_password:
        return jsonify({"status": "error", "message": "Passwords do not match"}), 400

    if len(new_password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters"}), 400

    try:
        with get_cursor() as cur:

            # 🔍 FETCH USER
            cur.execute("""
                SELECT password FROM users WHERE id = %s
            """, (user_id,))
            user = cur.fetchone()

            if not user:
                return jsonify({"status": "error", "message": "User not found"}), 404

            stored_password = user["password"]

            # 🔥 CASE 1: GOOGLE USER (NO PASSWORD YET)
            if not stored_password:
                # 👉 skip current password check
                hashed_password = generate_password_hash(new_password)

                cur.execute("""
                    UPDATE users SET password = %s WHERE id = %s
                """, (hashed_password, user_id))

                return jsonify({
                    "status": "success",
                    "message": "Password set successfully (Google account upgraded)"
                })

            # 🔥 CASE 2: NORMAL USER

            if not current_password:
                return jsonify({
                    "status": "error",
                    "message": "Current password required"
                }), 400

            if not check_password_hash(stored_password, current_password):
                return jsonify({
                    "status": "error",
                    "message": "Invalid current password"
                }), 400

            if check_password_hash(stored_password, new_password):
                return jsonify({
                    "status": "error",
                    "message": "New password must be different"
                }), 400

            # 🔐 UPDATE PASSWORD
            hashed_password = generate_password_hash(new_password)

            cur.execute("""
                UPDATE users SET password = %s WHERE id = %s
            """, (hashed_password, user_id))

        return jsonify({
            "status": "success",
            "message": "Password updated successfully"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500