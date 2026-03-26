import re
from flask import Blueprint, render_template, session, request, redirect, flash, current_app, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import os
from werkzeug.utils import secure_filename
from app.db import get_db
from app.decorators import login_required, role_required
from app.db import get_cursor

student_bp = Blueprint("student", __name__)

PASSWORD_PATTERN = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$"
EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx"}


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
    conn = get_db()
    student_id = session.get("user_id")

    try:
        cur = get_cursor(conn)

        # 👤 USER
        cur.execute("""
            SELECT id, name, email, school, skills, created_at, password, cv_path
            FROM users
            WHERE id = %s AND role = 'student'
        """, (student_id,))
        user = cur.fetchone()

        if not user:
            flash("Student account was not found.", "error")
            return redirect("/logout")

        # 📄 APPLICATIONS
        cur.execute("""
            SELECT 
                a.id,
                a.status,
                a.score,
                a.evaluation_note,
                a.created_at,
                i.id AS internship_id,
                i.title,
                i.location,
                i.internship_type,
                i.stipend,
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
                s.id AS saved_id,
                s.created_at AS saved_at,
                i.id AS internship_id,
                i.title,
                i.location,
                i.internship_type,
                i.stipend,
                i.deadline,
                c.name AS company_name,
                EXISTS(
                    SELECT 1
                    FROM applications a
                    WHERE a.student_id = %s AND a.internship_id = i.id
                ) AS is_applied
            FROM saved_internships s
            JOIN internships i ON s.internship_id = i.id
            LEFT JOIN companies c ON i.company_id = c.id
            WHERE s.student_id = %s AND i.approved = TRUE
            ORDER BY s.created_at DESC
        """, (student_id, student_id))
        saved_jobs = cur.fetchall()

        # 🔍 EXPLORE INTERNSHIPS
        cur.execute("""
            SELECT 
                i.id,
                i.title,
                i.location,
                i.internship_type,
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

        # 📊 STATS
        total_applications = len(applications)
        reviewing_count = sum(1 for a in applications if a["status"] in ["Yangi", "Ko'rib chiqilmoqda"])
        accepted_count = sum(1 for a in applications if a["status"] == "Qabul qilindi")
        rejected_count = sum(1 for a in applications if a["status"] == "Rad etildi")
        saved_count = len(saved_jobs)

        # 📈 PROFILE STRENGTH
        profile_fields = [
            user["name"],
            user["email"],
            user["school"],
            user["skills"]
        ]
        filled = sum(1 for field in profile_fields if field and str(field).strip())
        profile_strength = int((filled / len(profile_fields)) * 100) if profile_fields else 0

        recent_activity = applications[:5]

        return render_template(
            "student/student-landing.html",
            user=user,
            applications=applications,
            saved_jobs=saved_jobs,
            explore_internships=explore_internships,
            total_applications=total_applications,
            reviewing_count=reviewing_count,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            saved_count=saved_count,
            profile_strength=profile_strength,
            recent_activity=recent_activity
        )

    finally:
        conn.close()

@student_bp.route("/apply")
@login_required
@role_required("student")
def apply_page():
    conn = get_db()
    try:
        cur = get_cursor(conn)

        cur.execute("""
            SELECT 
                internships.*,
                companies.name AS company
            FROM internships
            LEFT JOIN companies ON companies.id = internships.company_id
            WHERE internships.approved = TRUE
            ORDER BY internships.created_at DESC
        """)
        internships = cur.fetchall()

        return render_template("apply.html", internships=internships)

    finally:
        conn.close()


@student_bp.route("/apply/<int:internship_id>", methods=["POST"])
@login_required
@role_required("student")
def apply(internship_id):
    conn = get_db()
    student_id = session["user_id"]

    try:
        cur = get_cursor(conn)

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

        # 📝 INSERT APPLICATION
        cur.execute("""
            INSERT INTO applications (student_id, internship_id, status)
            VALUES (%s, %s, %s)
        """, (student_id, internship_id, "Yangi"))

        # 📊 ANALYTICS
        cur.execute("""
            SELECT id FROM analytics WHERE internship_id = %s
        """, (internship_id,))
        analytics_row = cur.fetchone()

        if analytics_row:
            cur.execute("""
                UPDATE analytics
                SET applications = applications + 1
                WHERE internship_id = %s
            """, (internship_id,))
        else:
            cur.execute("""
                INSERT INTO analytics (internship_id, views, applications)
                VALUES (%s, 0, 1)
            """, (internship_id,))

        conn.commit()

        current_app.logger.info(
            "Student %s applied to internship %s",
            student_id,
            internship_id
        )

        flash("Application submitted successfully.", "success")
        return redirect(url_for("student.student_dashboard"))

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

@student_bp.route("/save/<int:internship_id>", methods=["POST"])
@login_required
@role_required("student")
def save_internship(internship_id):
    conn = get_db()
    student_id = session["user_id"]

    try:
        cur = get_cursor(conn)

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

        conn.commit()

        current_app.logger.info(
            "Student %s saved internship %s",
            student_id,
            internship_id
        )

        flash("Internship saved successfully.", "success")
        return redirect(url_for("student.student_dashboard"))

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


@student_bp.route("/unsave/<int:internship_id>", methods=["POST"])
@login_required
@role_required("student")
def unsave_internship(internship_id):
    conn = get_db()
    student_id = session["user_id"]

    try:
        cur = get_cursor(conn)

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

        conn.commit()

        current_app.logger.info(
            "Student %s unsaved internship %s",
            student_id,
            internship_id
        )

        flash("Internship removed from saved list.", "success")
        return redirect(url_for("student.student_dashboard"))

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


@student_bp.route("/profile/update", methods=["POST"])
@login_required
@role_required("student")
def update_profile():
    conn = get_db()
    student_id = session["user_id"]

    name = (request.form.get("name") or "").strip()
    email = normalize_email(request.form.get("email"))
    school = (request.form.get("school") or "").strip()
    skills = (request.form.get("skills") or "").strip()

    # 🔐 VALIDATION
    if not name or not email:
        flash("Name and email are required.", "error")
        return redirect(url_for("student.student_dashboard"))

    if not is_valid_email(email):
        flash("Invalid email format.", "error")
        return redirect(url_for("student.student_dashboard"))

    try:
        cur = get_cursor(conn)

        # 🔍 CHECK EMAIL UNIQUENESS
        cur.execute("""
            SELECT id FROM users
            WHERE LOWER(email) = LOWER(%s) AND id != %s
        """, (email, student_id))
        existing = cur.fetchone()

        if existing:
            flash("This email is already in use.", "error")
            return redirect(url_for("student.student_dashboard"))

        # ✏️ UPDATE PROFILE
        cur.execute("""
            UPDATE users
            SET name = %s, email = %s, school = %s, skills = %s
            WHERE id = %s
        """, (name, email, school, skills, student_id))

        conn.commit()

        # 🧠 UPDATE SESSION (nice touch)
        session["user_name"] = name

        current_app.logger.info(
            "Student %s updated profile",
            student_id
        )

        flash("Profile updated successfully.", "success")
        return redirect(url_for("student.student_dashboard"))

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


@student_bp.route("/profile/change-password", methods=["POST"])
@login_required
@role_required("student")
def change_password():
    conn = get_db()
    student_id = session["user_id"]

    current_password = (request.form.get("current_password") or "").strip()
    new_password = (request.form.get("new_password") or "").strip()
    confirm_password = (request.form.get("confirm_password") or "").strip()

    try:
        cur = get_cursor(conn)

        # 👤 FETCH USER
        cur.execute("""
            SELECT id, password
            FROM users
            WHERE id = %s AND role = 'student'
        """, (student_id,))
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
        """, (hashed_password, student_id))

        conn.commit()

        current_app.logger.info(
            "Student %s changed password",
            student_id
        )

        flash("Password changed successfully.", "success")
        return redirect(url_for("student.student_dashboard"))

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

@student_bp.route("/profile/upload-cv", methods=["POST"])
@login_required
@role_required("student")
def upload_cv():
    UPLOAD_FOLDER = os.path.join(current_app.root_path, "..", "static", "uploads", "cv")
    UPLOAD_FOLDER = os.path.abspath(UPLOAD_FOLDER)

    file = request.files.get("cv")
    student_id = session.get("user_id")

    # ❌ VALIDATION
    if not file or file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("student.student_dashboard"))

    if not allowed_file(file.filename):
        flash("Only PDF, DOC, DOCX allowed.", "error")
        return redirect(url_for("student.student_dashboard"))

    # 📏 FILE SIZE CHECK
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)

    if size > 5 * 1024 * 1024:
        flash("File too large (max 5MB).", "error")
        return redirect(url_for("student.student_dashboard"))

    # 🔐 SAFE FILENAME
    filename = secure_filename(file.filename)
    filename = f"user_{student_id}_{filename}"

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    db_path = f"/static/uploads/cv/{filename}"

    conn = get_db()

    try:
        cur = get_cursor(conn)

        # 🔍 GET OLD CV
        cur.execute("""
            SELECT cv_path FROM users WHERE id = %s
        """, (student_id,))
        old = cur.fetchone()

        # 🧹 REMOVE OLD FILE (SAFE)
        if old and old["cv_path"]:
            try:
                old_path = os.path.join(
                    current_app.root_path,
                    "..",
                    old["cv_path"].lstrip("/")
                )
                old_path = os.path.abspath(old_path)

                if os.path.exists(old_path):
                    os.remove(old_path)
            except Exception:
                current_app.logger.warning("Failed to delete old CV")

        # 💾 SAVE NEW FILE
        file.save(filepath)

        # 📝 UPDATE DB
        cur.execute("""
            UPDATE users
            SET cv_path = %s
            WHERE id = %s
        """, (db_path, student_id))

        conn.commit()

        flash("CV uploaded successfully!", "success")

    except Exception:
        conn.rollback()
        flash("Upload failed.", "error")
        raise

    finally:
        conn.close()

    current_app.logger.info(
        "Student %s uploaded CV",
        student_id
    )

    return redirect(url_for("student.student_dashboard"))