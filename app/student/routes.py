import re
from flask import Blueprint, render_template, session, request, redirect, flash, current_app, url_for,jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import os
from werkzeug.utils import secure_filename
from app.db import get_db
from app.decorators import login_required, role_required
from app.db import get_cursor
import json

student_bp = Blueprint("student", __name__)

PASSWORD_PATTERN = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$"
EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx"}
UPLOAD_FOLDER = "static/uploads/cv"
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

ALLOWED_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "doc", "docx"
}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS




def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def normalize_email(email):
    return (email or "").strip().lower()


def is_valid_email(email):
    return re.match(EMAIL_PATTERN, email or "") is not None


def is_valid_password(password):
    return re.match(PASSWORD_PATTERN, password or "") is not None


@student_bp.route("/student-dashboard")
@login_required
@role_required("student")
def student_dashboard():
    user_id = session.get("user_id")

    with get_cursor() as cur:

        # 👤 USER + STUDENT JOIN
        cur.execute("""
            SELECT 
                u.id, u.name, u.email, u.created_at, u.password,
                s.id AS student_id,
                s.phone, s.telegram, s.location, s.school, s.grade,
                s.linkedin, s.github, s.bio,
                s.program, s.gpa, s.subjects
            FROM users u
            JOIN students s ON s.user_id = u.id
            WHERE u.id = %s
        """, (user_id,))
        user = cur.fetchone()

        if not user:
            flash("Student account was not found.", "error")
            return redirect("/logout")

        student_id = user["student_id"]

        # 📄 GET CV FILE
        cur.execute("""
            SELECT file_url
            FROM user_files
            WHERE user_id = %s AND file_type = 'cv'
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))

        cv = cur.fetchone()
        user["cv_path"] = cv["file_url"] if cv else None

        # 🧠 SKILLS
        cur.execute("""
            SELECT sk.id, sk.name
            FROM student_skills ss
            JOIN skills sk ON sk.id = ss.skill_id
            WHERE ss.student_id = %s
        """, (student_id,))
        skills = cur.fetchall()

        # 🧠 EXPERIENCES
        cur.execute("""
            SELECT * FROM experiences 
            WHERE student_id=%s 
            ORDER BY id DESC
        """, (student_id,))
        experiences = cur.fetchall()

        for exp in experiences:
            if exp.get("grade_levels"):
                try:
                    data = exp["grade_levels"]
                    if isinstance(data, str):
                        data = json.loads(data)

                    exp["grades"] = data.get("grades", [])
                    exp["hours"] = data.get("hours_per_week")
                    exp["weeks"] = data.get("weeks_per_year")

                except:
                    exp["grades"] = []
                    exp["hours"] = None
                    exp["weeks"] = None

        # 📄 APPLICATIONS
        cur.execute("""
            SELECT 
                a.id, a.status, a.score, a.evaluation_note, a.created_at,
                i.id AS internship_id, i.title, i.location,
                i.type, i.stipend,
                c.name AS company_name
            FROM applications a
            JOIN internships i ON a.internship_id = i.id
            LEFT JOIN companies c ON i.company_id = c.id
            WHERE a.student_id = %s
            ORDER BY a.created_at DESC
        """, (student_id,))
        applications = cur.fetchall()

        # 💾 SAVED JOBS
        cur.execute("""
            SELECT 
                s.internship_id AS saved_id, 
                s.created_at AS saved_at,
                i.id AS internship_id, 
                i.title, 
                i.location,
                i.type AS internship_type, 
                i.stipend, 
                i.deadline,
                c.name AS company_name,
                EXISTS(
                    SELECT 1 FROM applications a
                    WHERE a.student_id = %s AND a.internship_id = i.id
                ) AS is_applied
            FROM saved_internships s
            JOIN internships i ON s.internship_id = i.id
            LEFT JOIN companies c ON i.company_id = c.id
            WHERE s.student_id = %s AND i.approved = TRUE
            ORDER BY s.created_at DESC
        """, (student_id, student_id))

        saved_jobs = cur.fetchall()


        # 🔍 EXPLORE
        cur.execute("""
            SELECT 
                i.id, 
                i.title, 
                i.location, 
                i.type AS internship_type,
                i.stipend, 
                i.deadline,
                c.id AS company_id, 
                c.name AS company_name,
                c.logo_url AS company_logo, 
                c.industry,
                c.address, 
                c.description AS company_description,
                c.phone1, 
                c.website,
                EXISTS(
                    SELECT 1 FROM saved_internships s
                    WHERE s.student_id = %s AND s.internship_id = i.id
                ) AS is_saved,
                EXISTS(
                    SELECT 1 FROM applications a
                    WHERE a.student_id = %s AND a.internship_id = i.id
                ) AS is_applied
            FROM internships i
            LEFT JOIN companies c ON i.company_id = c.id
            WHERE i.approved = TRUE
            ORDER BY i.created_at DESC
            LIMIT 12
        """, (student_id, student_id))

        explore_internships = cur.fetchall()

        # 📊 STATS (ENUM FIXED)
        total_applications = len(applications)
        reviewing_count = sum(1 for a in applications if a["status"] in ["new", "reviewing"])
        accepted_count = sum(1 for a in applications if a["status"] == "accepted")
        rejected_count = sum(1 for a in applications if a["status"] == "rejected")
        saved_count = len(saved_jobs)

        # 📈 PROFILE STRENGTH
        profile_fields = [
            user["name"], user["email"], user["school"],
            user["location"], user["grade"], user["phone"],
            user["linkedin"]
        ]

        filled = sum(1 for f in profile_fields if f and str(f).strip())
        base_score = int((filled / len(profile_fields)) * 70)

        extra_score = len(skills) * 5 + len(experiences) * 10
        profile_strength = min(base_score + extra_score, 100)

        return render_template(
            "student/student-dashboard.html",
            user=user,
            skills=skills,
            experiences=experiences,
            applications=applications,
            saved_jobs=saved_jobs,
            explore_internships=explore_internships,
            total_applications=total_applications,
            reviewing_count=reviewing_count,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            saved_count=saved_count,
            profile_strength=profile_strength,
            recent_activity=applications[:10]
        )


@student_bp.route("/profile/update-skills", methods=["POST"])
@login_required
@role_required("student")
def update_skills():
    user_id = session["user_id"]
    skills = request.form.getlist("skills[]")

    with get_cursor() as cur:

        # ✅ GET real student_id
        cur.execute("SELECT id FROM students WHERE user_id=%s", (user_id,))
        student = cur.fetchone()

        if not student:
            return jsonify({"success": False, "error": "Student not found"}), 404

        student_id = student["id"]

        # ❌ REMOVE OLD RELATIONS
        cur.execute("""
            DELETE FROM student_skills
            WHERE student_id = %s
        """, (student_id,))

        # ✅ INSERT NEW SKILLS
        for skill_name in skills:
            skill_name = (skill_name or "").strip()
            if not skill_name:
                continue

            # 🔍 Check if skill exists
            cur.execute("""
                SELECT id FROM skills WHERE name = %s
            """, (skill_name,))
            existing = cur.fetchone()

            if existing:
                skill_id = existing["id"]
            else:
                # ➕ Create new skill
                cur.execute("""
                    INSERT INTO skills (name)
                    VALUES (%s)
                    RETURNING id
                """, (skill_name,))
                skill_id = cur.fetchone()["id"]

            # 🔗 Link student ↔ skill
            cur.execute("""
                INSERT INTO student_skills (student_id, skill_id)
                VALUES (%s, %s)
            """, (student_id, skill_id))

    return jsonify({"success": True})

@student_bp.route("/profile/delete-skill/<int:id>", methods=["POST"])
@login_required
@role_required("student")
def delete_skill(id):
    user_id = session["user_id"]

    with get_cursor() as cur:

        # ✅ GET real student_id
        cur.execute("SELECT id FROM students WHERE user_id=%s", (user_id,))
        student = cur.fetchone()

        if not student:
            return jsonify({"success": False, "error": "Student not found"}), 404

        student_id = student["id"]

        # ❌ DO NOT delete from skills table
        # ✅ ONLY remove relation
        cur.execute("""
            DELETE FROM student_skills
            WHERE student_id = %s AND skill_id = %s
        """, (student_id, id))

    return jsonify({"success": True})

@student_bp.route("/profile/add-experience", methods=["POST"])
@login_required
@role_required("student")
def add_experience():
    user_id = session["user_id"]

    with get_cursor() as cur:

        # 🔍 GET student_id
        cur.execute("SELECT id FROM students WHERE user_id=%s", (user_id,))
        student = cur.fetchone()

        if not student:
            return jsonify({"error": "Student not found"}), 404

        student_id = student["id"]

        import json

        # ✅ GET DATA
        grades = request.form.getlist("grades[]")
        hours = request.form.get("hours_per_week")
        weeks = request.form.get("weeks_per_year")
        uni_years = request.form.getlist("university_years[]")

        # ✅ BUILD JSON
        grade_data = json.dumps({
            "grades": [int(g) for g in grades] if grades else [],
            "university_years": [int(u) for u in uni_years] if uni_years else [],
            "hours_per_week": int(hours) if hours else None,
            "weeks_per_year": int(weeks) if weeks else None
        })

        # ✅ INSERT
        cur.execute("""
            INSERT INTO experiences
            (student_id, title, organization, description, grade_levels, is_current, role)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            student_id,
            request.form.get("title"),
            request.form.get("organization"),
            request.form.get("description"),
            grade_data,
            request.form.get("current") == "true",
            request.form.get("role") or None
        ))

        print(request.form)  # debug

        new_id = cur.fetchone()["id"]

    return jsonify({
        "success": True,
        "id": new_id
    })

@student_bp.route("/profile/delete-experience/<int:id>", methods=["POST"])
@login_required
@role_required("student")
def delete_experience(id):
    user_id = session["user_id"]

    with get_cursor() as cur:

        # ✅ GET real student_id
        cur.execute("SELECT id FROM students WHERE user_id=%s", (user_id,))
        student = cur.fetchone()

        if not student:
            return jsonify({"success": False, "error": "Student not found"}), 404

        student_id = student["id"]

        # ✅ DELETE (FIXED COLUMN)
        cur.execute("""
            DELETE FROM experiences
            WHERE id = %s AND student_id = %s
        """, (id, student_id))

    return jsonify({"success": True})

@student_bp.route("/apply")
@login_required
@role_required("student")
def apply_page():

    with get_cursor() as cur:

        cur.execute("""
            SELECT 
                i.*,
                c.name AS company
            FROM internships i
            LEFT JOIN companies c ON c.id = i.company_id
            WHERE i.approved = TRUE
            ORDER BY i.created_at DESC
        """)
        internships = cur.fetchall()

    return render_template("apply.html", internships=internships)


@student_bp.route("/apply/<int:internship_id>", methods=["POST"])
@login_required
@role_required("student")
def apply(internship_id):
    user_id = session["user_id"]

    # ✅ GET MOTIVATION
    motivation = (request.form.get("motivation") or "").strip()

    with get_cursor() as cur:

        # ✅ GET real student_id
        cur.execute("SELECT id FROM students WHERE user_id=%s", (user_id,))
        student = cur.fetchone()

        if not student:
            flash("Student not found.", "error")
            return redirect(url_for("student.student_dashboard"))

        student_id = student["id"]

        # 🔍 CHECK INTERNSHIP
        cur.execute("""
            SELECT id
            FROM internships
            WHERE id = %s AND approved = TRUE
        """, (internship_id,))
        internship = cur.fetchone()

        if not internship:
            flash("Internship not found.", "error")
            return redirect(url_for("student.student_dashboard"))

        # 🔍 CHECK EXISTING APPLICATION
        cur.execute("""
            SELECT id
            FROM applications
            WHERE student_id = %s AND internship_id = %s
        """, (student_id, internship_id))
        existing = cur.fetchone()

        if existing:
            flash("You already applied to this internship.", "error")
            return redirect(url_for("student.student_dashboard"))

        # ❗ VALIDATION
        if len(motivation) < 20:
            flash("Please write a meaningful answer.", "error")
            return redirect(url_for("student.student_dashboard"))

        # ✅ INSERT (NO STATUS — uses DEFAULT 'new')
        cur.execute("""
            INSERT INTO applications (student_id, internship_id, motivation)
            VALUES (%s, %s, %s)
        """, (student_id, internship_id, motivation))

        # 📊 ANALYTICS
        cur.execute("""
            SELECT internship_id FROM internship_stats WHERE internship_id = %s
        """, (internship_id,))
        analytics_row = cur.fetchone()

        if analytics_row:
            cur.execute("""
                UPDATE internship_stats 
                SET applications = applications + 1
                WHERE internship_id = %s
            """, (internship_id,))
        else:
            cur.execute("""
                INSERT INTO internship_stats (internship_id, views, applications)
                VALUES (%s, 0, 1)
            """, (internship_id,))

    flash("Application submitted successfully.", "success")
    return redirect(url_for("student.student_dashboard"))

@student_bp.route("/save/<int:internship_id>", methods=["POST"])
@login_required
@role_required("student")
def save_internship(internship_id):
    user_id = session["user_id"]

    with get_cursor() as cur:

        # ✅ GET real student_id
        cur.execute("SELECT id FROM students WHERE user_id=%s", (user_id,))
        student = cur.fetchone()

        if not student:
            flash("Student not found.", "error")
            return redirect(url_for("student.student_dashboard"))

        student_id = student["id"]

        # 🔍 CHECK INTERNSHIP
        cur.execute("""
            SELECT id
            FROM internships
            WHERE id = %s AND approved = TRUE
        """, (internship_id,))
        internship = cur.fetchone()

        if not internship:
            flash("Internship not found.", "error")
            return redirect(url_for("student.student_dashboard"))

        # 🔍 CHECK EXISTING SAVE
        cur.execute("""
            SELECT id
            FROM saved_internships
            WHERE student_id = %s AND internship_id = %s
        """, (student_id, internship_id))
        existing = cur.fetchone()

        if existing:
            flash("This internship is already saved.", "error")
            return redirect(url_for("student.student_dashboard"))

        # 💾 INSERT SAVE
        cur.execute("""
            INSERT INTO saved_internships (student_id, internship_id)
            VALUES (%s, %s)
        """, (student_id, internship_id))

        current_app.logger.info(
            "Student %s saved internship %s",
            student_id,
            internship_id
        )

    flash("Internship saved successfully.", "success")
    return redirect(url_for("student.student_dashboard"))


@student_bp.route("/unsave/<int:internship_id>", methods=["POST"])
@login_required
@role_required("student")
def unsave_internship(internship_id):
    user_id = session["user_id"]

    with get_cursor() as cur:

        # ✅ GET real student_id
        cur.execute("SELECT id FROM students WHERE user_id=%s", (user_id,))
        student = cur.fetchone()

        if not student:
            flash("Student not found.", "error")
            return redirect(url_for("student.student_dashboard"))

        student_id = student["id"]

        # 🔍 CHECK EXISTENCE
        cur.execute("""
            SELECT id
            FROM saved_internships
            WHERE student_id = %s AND internship_id = %s
        """, (student_id, internship_id))
        existing = cur.fetchone()

        if not existing:
            flash("Saved internship not found.", "error")
            return redirect(url_for("student.student_dashboard"))

        # 🗑 DELETE
        cur.execute("""
            DELETE FROM saved_internships
            WHERE student_id = %s AND internship_id = %s
        """, (student_id, internship_id))

        current_app.logger.info(
            "Student %s unsaved internship %s",
            student_id,
            internship_id
        )

    flash("Internship removed from saved list.", "success")
    return redirect(url_for("student.student_dashboard"))


@student_bp.route("/profile/update", methods=["POST"])
@login_required
@role_required("student")
def update_profile():
    user_id = session["user_id"]

    # 📥 INPUTS
    name = (request.form.get("name") or "").strip()
    email = normalize_email(request.form.get("email"))
    school = (request.form.get("school") or "").strip()
    location = (request.form.get("location") or "").strip()
    grade = (request.form.get("grade") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    linkedin = (request.form.get("linkedin") or "").strip()
    telegram = (request.form.get("telegram") or "").strip()

    # ✅ VALIDATION
    if not name or not email:
        return jsonify({"success": False, "error": "Name and email required"})

    if not is_valid_email(email):
        return jsonify({"success": False, "error": "Invalid email"})

    with get_cursor() as cur:

        # 🔍 CHECK EMAIL UNIQUENESS
        cur.execute("""
            SELECT id FROM users
            WHERE LOWER(email) = LOWER(%s) AND id != %s
        """, (email, user_id))

        if cur.fetchone():
            return jsonify({"success": False, "error": "Email already in use"})

        # ✅ UPDATE users (AUTH ONLY)
        cur.execute("""
            UPDATE users
            SET name = %s, email = %s
            WHERE id = %s
        """, (name, email, user_id))

        # ✅ UPDATE students (PROFILE DATA)
        cur.execute("""
            UPDATE students
            SET school = %s,
                location = %s,
                grade = %s,
                phone = %s,
                linkedin = %s,
                telegram = %s
            WHERE user_id = %s
        """, (
            school, location, grade,
            phone, linkedin, telegram,
            user_id
        ))

    # ✅ SESSION UPDATE
    session["user_name"] = name

    return jsonify({"success": True})

@student_bp.route("/profile/change-password", methods=["POST"])
@login_required
@role_required("student")
def change_password():
    user_id = session["user_id"]

    current_password = (request.form.get("current_password") or "").strip()
    new_password = (request.form.get("new_password") or "").strip()
    confirm_password = (request.form.get("confirm_password") or "").strip()

    with get_cursor() as cur:

        # 👤 FETCH USER (FIXED)
        cur.execute("""
            SELECT id, password
            FROM users
            WHERE id = %s
        """, (user_id,))
        user = cur.fetchone()

        if not user:
            flash("Student account was not found.", "error")
            return redirect("/logout")

        # 🔐 GOOGLE ACCOUNT CHECK
        if not user["password"]:
            flash("This account uses Google login. Password change is not available here.", "error")
            return redirect(url_for("student.student_dashboard"))

        # 🔐 VALIDATION
        if not current_password or not new_password or not confirm_password:
            flash("All password fields are required.", "error")
            return redirect(url_for("student.student_dashboard"))

        if not check_password_hash(user["password"], current_password):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("student.student_dashboard"))

        if not is_valid_password(new_password):
            flash("New password must contain uppercase, lowercase, number, symbol and be at least 8 characters.", "error")
            return redirect(url_for("student.student_dashboard"))

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect(url_for("student.student_dashboard"))

        if current_password == new_password:
            flash("New password must be different from the current password.", "error")
            return redirect(url_for("student.student_dashboard"))

        # 🔐 HASH NEW PASSWORD
        hashed_password = generate_password_hash(new_password)

        # 🔄 UPDATE PASSWORD
        cur.execute("""
            UPDATE users
            SET password = %s
            WHERE id = %s
        """, (hashed_password, user_id))

        current_app.logger.info(
            "User %s changed password",
            user_id
        )

    flash("Password changed successfully.", "success")
    return redirect(url_for("student.student_dashboard"))

@student_bp.route("/profile/update-academic", methods=["POST"])
@login_required
@role_required("student")
def update_academic():
    user_id = session["user_id"]

    program = (request.form.get("program") or "").strip()
    gpa = (request.form.get("gpa") or "").strip()
    subjects = (request.form.get("subjects") or "").strip()

    # 🔐 VALIDATION
    if gpa:
        try:
            gpa_val = float(gpa)
            if gpa_val < 0 or gpa_val > 5:
                return jsonify({"success": False, "error": "GPA must be between 0 and 5"})
        except:
            return jsonify({"success": False, "error": "Invalid GPA format"})

    with get_cursor() as cur:

        # 🔍 Check existence
        cur.execute("SELECT id FROM students WHERE user_id = %s", (user_id,))
        existing = cur.fetchone()

        if existing:
            cur.execute("""
                UPDATE students
                SET program = %s,
                    gpa = %s,
                    subjects = %s
                WHERE user_id = %s
            """, (program, gpa, subjects, user_id))
        else:
            cur.execute("""
                INSERT INTO students (user_id, program, gpa, subjects)
                VALUES (%s, %s, %s, %s)
            """, (user_id, program, gpa, subjects))

    return jsonify({"success": True})

@student_bp.route("/profile/upload-cv", methods=["POST"])
@login_required
@role_required("student")
def upload_cv():
    user_id = session["user_id"]

    file = request.files.get("cv")

    if not file or file.filename == "":
        return jsonify({"success": False, "message": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({
            "success": False,
            "message": "Invalid file type. Allowed: PDF, PNG, JPG, DOC, DOCX"
        }), 400

    # 🔐 Size check
    file.seek(0, os.SEEK_END)
    file_length = file.tell()
    file.seek(0)

    if file_length > MAX_FILE_SIZE:
        return jsonify({
            "success": False,
            "message": "File too large (max 5MB)"
        }), 400

    # 🧼 Filename
    filename = secure_filename(file.filename)
    unique_filename = f"cv_{user_id}_{filename}"

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
    file.save(filepath)

    file_url = f"/{UPLOAD_FOLDER}/{unique_filename}"

    # 💾 DB
    with get_cursor() as cur:
        cur.execute("""
            DELETE FROM user_files
            WHERE user_id = %s AND file_type = 'cv'
        """, (user_id,))

        cur.execute("""
            INSERT INTO user_files (user_id, file_url, file_type)
            VALUES (%s, %s, 'cv')
        """, (user_id, file_url))

    return jsonify({
        "success": True,
        "message": "CV uploaded successfully!",
        "file_url": file_url,
        "filename": filename
    })

@student_bp.route("/profile/update-experience/<int:id>", methods=["POST"])
@login_required
def update_experience(id):
    user_id = session["user_id"]

    import json

    grades = request.form.getlist("grades[]")
    uni_years = request.form.getlist("university_years[]")

    hours = request.form.get("hours_per_week")
    weeks = request.form.get("weeks_per_year")

    grade_data = json.dumps({
        "grades": [int(g) for g in grades] if grades else [],
        "university_years": [int(u) for u in uni_years] if uni_years else [],
        "hours_per_week": int(hours) if hours else None,
        "weeks_per_year": int(weeks) if weeks else None
    })

    with get_cursor() as cur:
        cur.execute("""
            UPDATE experiences
            SET title=%s,
                organization=%s,
                role=%s,
                description=%s,
                is_current=%s,
                grade_levels=%s
            WHERE id=%s
            AND student_id = (
                SELECT id FROM students WHERE user_id=%s
            )
        """, (
            request.form.get("title"),
            request.form.get("organization"),
            request.form.get("role"),
            request.form.get("description"),
            request.form.get("current") == "true",
            grade_data,
            id,
            user_id
        ))

    return jsonify({"success": True})