from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from app.db import get_db
from app.decorators import login_required, role_required
from app.db import get_cursor
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ================================
# HELPER: HANDLE AJAX OR NORMAL
# ================================
def handle_response(message, data=None):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        response = {"success": True}
        if data:
            response.update(data)
        return jsonify(response)

    flash(message, "success")
    return redirect(request.referrer or url_for("admin.overview"))


# ================================
# OVERVIEW (DASHBOARD)
# ================================
@admin_bp.route("/")
@login_required
@role_required("admin")
def overview():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        # 📊 ALL STATS IN ONE QUERY (FAST 🚀)
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM users) AS total_users,
                (SELECT COUNT(*) FROM users WHERE role = 'student') AS total_students,
                (SELECT COUNT(*) FROM companies) AS total_companies,
                (SELECT COUNT(*) FROM companies WHERE verified = TRUE) AS verified_companies,
                (SELECT COUNT(*) FROM companies WHERE verified = FALSE) AS pending_companies,
                (SELECT COUNT(*) FROM users WHERE banned = TRUE) AS banned_users,
                (SELECT COUNT(*) FROM internships) AS total_internships,
                (SELECT COUNT(*) FROM internships WHERE approved = TRUE) AS approved_internships,
                (SELECT COUNT(*) FROM internships WHERE approved = FALSE) AS pending_internships,
                (SELECT COUNT(*) FROM applications) AS total_applications
        """)
        stats = cur.fetchone()

        # 📈 INTERNSHIPS PER COMPANY
        cur.execute("""
            SELECT companies.name AS company_name, COUNT(internships.id) AS total
            FROM companies
            LEFT JOIN internships ON internships.company_id = companies.id
            GROUP BY companies.id
            ORDER BY total DESC
            LIMIT 6
        """)
        internship_by_company_rows = cur.fetchall()

        chart_company_labels = [row["company_name"] for row in internship_by_company_rows]
        chart_company_data = [row["total"] for row in internship_by_company_rows]

        # 📊 APPLICATION STATUS
        cur.execute("""
            SELECT status, COUNT(*) AS total
            FROM applications
            GROUP BY status
        """)
        application_status_rows = cur.fetchall()

        chart_status_labels = [row["status"] for row in application_status_rows]
        chart_status_data = [row["total"] for row in application_status_rows]

        return render_template(
            "admin/overview.html",
            active="overview",
            stats=stats,
            chart_company_labels=chart_company_labels,
            chart_company_data=chart_company_data,
            chart_status_labels=chart_status_labels,
            chart_status_data=chart_status_data,
        )

    finally:
        conn.close()


# ================================
# USERS
# ================================
@admin_bp.route("/users")
@login_required
@role_required("admin")
def users():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        cur.execute("""
            SELECT id, name, email, role, banned, created_at
            FROM users
            ORDER BY created_at DESC
        """)
        users = cur.fetchall()

        return render_template(
            "admin/users.html",
            active="users",
            users=users
        )

    finally:
        conn.close()

# ================================
# COMPANIES
# ================================
@admin_bp.route("/companies")
@login_required
@role_required("admin")
def companies():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        cur.execute("""
            SELECT 
                companies.*,
                users.name AS owner_name,
                users.email AS owner_email
            FROM companies
            LEFT JOIN users ON users.id = companies.user_id
            ORDER BY companies.created_at DESC
        """)
        companies = cur.fetchall()

        return render_template(
            "admin/companies.html",
            active="companies",
            companies=companies
        )

    finally:
        conn.close()


# ================================
# INTERNSHIPS
# ================================
@admin_bp.route("/internships")
@login_required
@role_required("admin")
def internships():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        cur.execute("""
            SELECT 
                internships.*,
                companies.name AS company_name,
                COUNT(applications.id) AS applications_count
            FROM internships
            LEFT JOIN companies ON companies.id = internships.company_id
            LEFT JOIN applications ON applications.internship_id = internships.id
            GROUP BY internships.id, companies.name
            ORDER BY internships.created_at DESC
        """)
        internships = cur.fetchall()

        return render_template(
            "admin/internships.html",
            active="internships",
            internships=internships
        )

    finally:
        conn.close()

# ================================
# APPLICATIONS
# ================================
@admin_bp.route("/applications")
@login_required
@role_required("admin")
def applications():
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        cur.execute("""
            SELECT 
                applications.*,
                users.name AS student_name,
                internships.title AS internship_title
            FROM applications
            LEFT JOIN users ON users.id = applications.student_id
            LEFT JOIN internships ON internships.id = applications.internship_id
            ORDER BY applications.created_at DESC
            LIMIT 20
        """)
        recent_applications = cur.fetchall()

        return render_template(
            "admin/applications.html",
            active="applications",
            recent_applications=recent_applications
        )

    finally:
        conn.close()


# ================================
# ACTIONS (FULLY DYNAMIC)
# ================================

@admin_bp.route("/verify-company/<int:company_id>", methods=["POST"])
@login_required
@role_required("admin")
def verify_company(company_id):
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        # 🔄 UPDATE + VERIFY
        cur.execute("""
            UPDATE companies
            SET verified = TRUE
            WHERE id = %s
            RETURNING id
        """, (company_id,))

        updated = cur.fetchone()

        if not updated:
            return handle_response(
                "Company not found.",
                {"verified": False},
                status=404
            )

        conn.commit()

        return handle_response(
            "Kompaniya tasdiqlandi.",
            {"verified": True}
        )

    finally:
        conn.close()


@admin_bp.route("/unverify-company/<int:company_id>", methods=["POST"])
@login_required
@role_required("admin")
def unverify_company(company_id):
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        # 🔄 UPDATE + VERIFY
        cur.execute("""
            UPDATE companies
            SET verified = FALSE
            WHERE id = %s
            RETURNING id
        """, (company_id,))

        updated = cur.fetchone()

        if not updated:
            return handle_response(
                "Company not found.",
                {"verified": False},
                status=404
            )

        conn.commit()

        return handle_response(
            "Tasdiq bekor qilindi.",
            {"verified": False}
        )

    finally:
        conn.close()


@admin_bp.route("/approve-internship/<int:internship_id>", methods=["POST"])
@login_required
@role_required("admin")
def approve_internship(internship_id):
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        # 🔄 UPDATE + VERIFY
        cur.execute("""
            UPDATE internships
            SET approved = TRUE
            WHERE id = %s
            RETURNING id
        """, (internship_id,))

        updated = cur.fetchone()

        if not updated:
            return handle_response(
                "Internship not found.",
                {"approved": False},
                status=404
            )

        conn.commit()

        return handle_response(
            "Tasdiqlandi.",
            {"approved": True}
        )

    finally:
        conn.close()


@admin_bp.route("/unapprove-internship/<int:internship_id>", methods=["POST"])
@login_required
@role_required("admin")
def unapprove_internship(internship_id):
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        # 🔄 UPDATE + VERIFY
        cur.execute("""
            UPDATE internships
            SET approved = FALSE
            WHERE id = %s
            RETURNING id
        """, (internship_id,))

        updated = cur.fetchone()

        if not updated:
            return handle_response(
                "Internship not found.",
                {"approved": False},
                status=404
            )

        conn.commit()

        return handle_response(
            "Bekor qilindi.",
            {"approved": False}
        )

    finally:
        conn.close()

@admin_bp.route("/ban-user/<int:user_id>", methods=["POST"])
@login_required
@role_required("admin")
def ban_user(user_id):
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        # 🚫 PREVENT BANNING ADMINS
        cur.execute("""
            SELECT role FROM users WHERE id = %s
        """, (user_id,))
        user = cur.fetchone()

        if not user:
            return handle_response(
                "User not found.",
                {"banned": False},
                status=404
            )

        if user["role"] == "admin":
            return handle_response(
                "Admin cannot be banned.",
                {"banned": False},
                status=403
            )

        # 🔄 UPDATE + VERIFY
        cur.execute("""
            UPDATE users
            SET banned = TRUE
            WHERE id = %s
            RETURNING id
        """, (user_id,))

        updated = cur.fetchone()

        if not updated:
            return handle_response(
                "Ban failed.",
                {"banned": False},
                status=500
            )

        conn.commit()

        return handle_response(
            "Foydalanuvchi bloklandi.",
            {"banned": True}
        )

    finally:
        conn.close()


@admin_bp.route("/unban-user/<int:user_id>", methods=["POST"])
@login_required
@role_required("admin")
def unban_user(user_id):
    conn = get_db()

    try:
        cur = get_cursor(conn)  # 🔥 FIX

        # 🔍 CHECK USER
        cur.execute("""
            SELECT role FROM users WHERE id = %s
        """, (user_id,))
        user = cur.fetchone()

        if not user:
            return handle_response(
                "User not found.",
                {"banned": False},
                status=404
            )

        # 🚫 OPTIONAL: protect admin logic consistency
        if user["role"] == "admin":
            return handle_response(
                "Admin cannot be modified.",
                {"banned": False},
                status=403
            )

        # 🔄 UPDATE + VERIFY
        cur.execute("""
            UPDATE users
            SET banned = FALSE
            WHERE id = %s
            RETURNING id
        """, (user_id,))

        updated = cur.fetchone()

        if not updated:
            return handle_response(
                "Unban failed.",
                {"banned": False},
                status=500
            )

        conn.commit()

        return handle_response(
            "Foydalanuvchi tiklandi.",
            {"banned": False}
        )

    finally:
        conn.close()