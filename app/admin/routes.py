from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask import session, abort
from app.db import get_db
from app.decorators import login_required, role_required
from app.db import get_cursor
import secrets
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")



# ================================
# HELPER: HANDLE AJAX OR NORMAL
# ================================
def handle_response(message, data=None, status=200):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        response = {"success": True}
        if data:
            response.update(data)
        return jsonify(response), status    

    flash(message, "success")
    return redirect(request.referrer or url_for("admin.overview"))


# ================================
# OVERVIEW (DASHBOARD)
# ================================
@admin_bp.route("/")
@login_required
@role_required("admin")
def overview():
    user_email = (session.get("email") or "").strip().lower()

    ADMIN_EMAILS = {
        "uksherozbek@gmail.com",
        "dilmurodarslonbekov@gmail.com",
        "dilmurod023@pmkhiva.com"
    }

    if user_email not in ADMIN_EMAILS:
        abort(403)
    try:
        with get_cursor() as cur:
            # 📊 ALL STATS
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
                GROUP BY companies.id, companies.name
                ORDER BY total DESC
                LIMIT 10
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

    except Exception as e:
        return f"Error: {e}", 500

# ================================
# USERS
# ================================
@admin_bp.route("/users")
@login_required
@role_required("admin")
def users():
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT id, name, email, role, banned, created_at
                FROM users
                ORDER BY created_at DESC
            """)
            user_list = cur.fetchall()

            cur.execute("""
                SELECT id, name, email, phone, telegram, created_at
                FROM waitlist
                ORDER BY created_at DESC
            """)
            waitlist_users = cur.fetchall()

        return render_template(
            "admin/users.html",
            active="users",
            users=user_list,
            waitlist_users=waitlist_users
        )

    except Exception as e:
        print("ADMIN USERS ERROR:", e)
        return "Internal Server Error", 500
# ================================
# COMPANIES
# ================================
@admin_bp.route("/companies")
@login_required
@role_required("admin")
def companies():
    try:
        with get_cursor() as cur:
            cur.execute("""
                    SELECT 
                        companies.*,
                        users.name AS owner_name,
                        users.email AS owner_email,

                        (
                            SELECT access_code
                            FROM external_company_access
                            WHERE company_id = companies.id
                            AND is_active = TRUE
                            ORDER BY created_at DESC
                            LIMIT 1
                        ) AS access_code

                    FROM companies

                    LEFT JOIN users
                    ON users.id = companies.user_id

                    ORDER BY companies.created_at DESC
            """)
            company_list = cur.fetchall()

        return render_template(
            "admin/companies.html",
            active="companies",
            companies=company_list
        )

    except Exception as e:
        print("ADMIN COMPANIES ERROR:", e)
        return "Internal Server Error", 500
    
@admin_bp.route("/generate-company-code/<int:company_id>", methods=["POST"])
@login_required
@role_required("admin")
def generate_company_code(company_id):

    try:

        access_code = secrets.token_urlsafe(12)

        with get_cursor() as cur:

            # deactivate old codes
            cur.execute("""
                UPDATE external_company_access
                SET is_active = FALSE
                WHERE company_id = %s
            """, (company_id,))

            # create new code
            cur.execute("""
                INSERT INTO external_company_access (
                    company_id,
                    access_code,
                    created_by_admin
                )
                VALUES (%s,%s,%s)
                RETURNING access_code
            """, (
                company_id,
                access_code,
                session.get("user_id")
            ))

            code = cur.fetchone()

        return handle_response(
            "Access code generated.",
            {
                "success": True,
                "access_code": code["access_code"]
            }
        )

    except Exception as e:

        print("GENERATE CODE ERROR:", e)

        return handle_response(
            "Internal server error.",
            {"success": False},
            status=500
        )


# ================================
# INTERNSHIPS
# ================================
@admin_bp.route("/internships")
@login_required
@role_required("admin")
def internships():
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT 
                    internships.*,
                    companies.name AS company_name,
                    COUNT(applications.id) AS applications_count
                FROM internships
                LEFT JOIN companies ON companies.id = internships.company_id
                LEFT JOIN applications ON applications.internship_id = internships.id
                GROUP BY internships.id, companies.id, companies.name
                ORDER BY internships.created_at DESC
            """)
            internship_list = cur.fetchall()

        return render_template(
            "admin/internships.html",
            active="internships",
            internships=internship_list
        )

    except Exception as e:
        print("ADMIN INTERNSHIPS ERROR:", e)
        return "Internal Server Error", 500

# ================================
# APPLICATIONS
# ================================
@admin_bp.route("/applications")
@login_required
@role_required("admin")
def applications():
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT 
                    applications.*,
                    users.name AS student_name,
                    internships.title AS internship_title
                FROM applications
                LEFT JOIN students ON students.id = applications.student_id
                LEFT JOIN users ON users.id = students.user_id
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

    except Exception as e:
        print("ADMIN APPLICATIONS ERROR:", e)
        return "Internal Server Error", 500


# ================================
# ACTIONS (FULLY DYNAMIC)
# ================================

@admin_bp.route("/verify-company/<int:company_id>", methods=["POST"])
@login_required
@role_required("admin")
def verify_company(company_id):
    try:
        with get_cursor() as cur:
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

        return handle_response(
            "Kompaniya tasdiqlandi.",
            {"verified": True}
        )

    except Exception as e:
        print("VERIFY COMPANY ERROR:", e)
        return handle_response(
            "Internal error.",
            {"verified": False},
            status=500
        )


@admin_bp.route("/unverify-company/<int:company_id>", methods=["POST"])
@login_required
@role_required("admin")
def unverify_company(company_id):
    try:
        with get_cursor() as cur:
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

        return handle_response(
            "Tasdiq bekor qilindi.",
            {"verified": False}
        )

    except Exception as e:
        print("UNVERIFY COMPANY ERROR:", e)
        return handle_response(
            "Internal error.",
            {"verified": False},
            status=500
        )


@admin_bp.route("/approve-internship/<int:internship_id>", methods=["POST"])
@login_required
@role_required("admin")
def approve_internship(internship_id):
    try:
        with get_cursor() as cur:
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

        return handle_response(
            "Tasdiqlandi.",
            {"approved": True}
        )

    except Exception as e:
        print("APPROVE INTERNSHIP ERROR:", e)
        return handle_response(
            "Internal error.",
            {"approved": False},
            status=500
        )


@admin_bp.route("/unapprove-internship/<int:internship_id>", methods=["POST"])
@login_required
@role_required("admin")
def unapprove_internship(internship_id):
    try:
        with get_cursor() as cur:
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

        return handle_response(
            "Bekor qilindi.",
            {"approved": False}
        )

    except Exception as e:
        print("UNAPPROVE INTERNSHIP ERROR:", e)
        return handle_response(
            "Internal error.",
            {"approved": False},
            status=500
        )

@admin_bp.route("/ban-user/<int:user_id>", methods=["POST"])
@login_required
@role_required("admin")
def ban_user(user_id):
    try:
        with get_cursor() as cur:
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

            # 🔄 UPDATE
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

        return handle_response(
            "Foydalanuvchi bloklandi.",
            {"banned": True}
        )

    except Exception as e:
        print("BAN USER ERROR:", e)
        return handle_response(
            "Internal error.",
            {"banned": False},
            status=500
        )

@admin_bp.route("/unban-user/<int:user_id>", methods=["POST"])
@login_required
@role_required("admin")
def unban_user(user_id):
    try:
        with get_cursor() as cur:
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

            if user["role"] == "admin":
                return handle_response(
                    "Admin cannot be modified.",
                    {"banned": False},
                    status=403
                )

            # 🔄 UPDATE
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

        return handle_response(
            "Foydalanuvchi tiklandi.",
            {"banned": False}
        )

    except Exception as e:
        print("UNBAN USER ERROR:", e)
        return handle_response(
            "Internal error.",
            {"banned": False},
            status=500
        )
    
@admin_bp.route("/waitlist")
@login_required
@role_required("admin")
def waitlist_users():
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT id, name, email, phone, telegram, created_at
                FROM waitlist
                ORDER BY created_at DESC
            """)
            waitlist_users = cur.fetchall()

        return render_template(
            "admin/waitlist.html",
            active="waitlist",
            waitlist_users=waitlist_users
        )

    except Exception as e:
        print("ADMIN WAITLIST ERROR:", e)
        return "Internal Server Error", 500
    
@admin_bp.route("/create-internship")
@login_required
@role_required("admin")
def create_internship_page():

    try:
        with get_cursor() as cur:

            cur.execute("""
                SELECT id, name
                FROM companies
                WHERE verified = TRUE
                ORDER BY name
            """)

            companies = cur.fetchall()

        return render_template(
            "admin/create_internship.html",
            active="create_internship",
            companies=companies
        )

    except Exception as e:
        print("CREATE INTERNSHIP PAGE ERROR:", e)
        return "Internal Server Error", 500
    
@admin_bp.route("/create-internship", methods=["POST"])
@login_required
@role_required("admin")
def create_internship():

    try:
        company_id = request.form.get("company_id")
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()

        if not company_id or not title:
            return handle_response(
                "Missing required fields.",
                {"success": False},
                status=400
            )

        stipend = request.form.get("stipend") or 0

        with get_cursor() as cur:

            cur.execute("""
                INSERT INTO internships (
                    company_id,
                    title,
                    description,
                    location,
                    duration,
                    deadline,
                    stipend,
                    type,
                    approved,
                    source_type,
                    created_by_admin
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (
                company_id,
                title,
                description,
                request.form.get("location"),
                request.form.get("duration"),
                request.form.get("deadline"),
                stipend,
                request.form.get("type"),
                True,
                "admin",
                session.get("user_id")
            ))

            internship = cur.fetchone()

        return handle_response(
            "Internship created successfully.",
            {
                "success": True,
                "internship_id": internship["id"]
            }
        )

    except Exception as e:
        print("CREATE INTERNSHIP ERROR:", e)

        return handle_response(
            "Internal server error.",
            {"success": False},
            status=500
        )

@admin_bp.route("/create-company")
@login_required
@role_required("admin")
def create_company_page():

    return render_template(
        "admin/create_company.html",
        active="companies"
    )

@admin_bp.route("/create-company", methods=["POST"])
@login_required
@role_required("admin")
def create_company():

    try:

        name = (request.form.get("name") or "").strip()

        if not name:
            return handle_response(
                "Company name required.",
                {"success": False},
                status=400
            )

        with get_cursor() as cur:

            cur.execute("""
                INSERT INTO companies (
                    name,
                    phone1,
                    website,
                    description,
                    logo_url,
                    industry,
                    address,
                    verified,
                    public_visible
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (
                name,
                request.form.get("phone1"),
                request.form.get("website"),
                request.form.get("description"),
                request.form.get("logo_url"),
                request.form.get("industry"),
                request.form.get("address"),
                True,
                True
            ))

            company = cur.fetchone()

        return handle_response(
            "Company created successfully.",
            {
                "success": True,
                "company_id": company["id"]
            }
        )

    except Exception as e:

        print("CREATE COMPANY ERROR:", e)

        return handle_response(
            "Internal server error.",
            {"success": False},
            status=500
        )