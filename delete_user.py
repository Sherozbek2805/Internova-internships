from app.db import get_cursor

# ======================================
# USERS TO DELETE
# ======================================

EMAILS_TO_DELETE = [
    "sherozbek106@gmail.com",
    "elyorjonibragimov628@gmail.com"
]

# ======================================
# SAFETY MODE
# ======================================

# True  -> only prints what WOULD happen
# False -> actually deletes
DRY_RUN = False

# ======================================
# DELETE USER
# ======================================

def delete_user_by_email(email):

    with get_cursor() as cur:

        # --------------------------------------
        # FIND USER
        # --------------------------------------

        cur.execute("""
            SELECT id, role, email
            FROM users
            WHERE LOWER(email) = LOWER(%s)
        """, (email,))

        user = cur.fetchone()

        if not user:
            print(f"❌ User not found: {email}")
            return

        user_id = user["id"]
        role = (user["role"] or "").lower()

        print(f"\n⚠️ Found user:")
        print(f"   Email: {user['email']}")
        print(f"   Role : {role}")
        print(f"   ID   : {user_id}")

        # --------------------------------------
        # PROTECT ADMINS
        # --------------------------------------

        if role == "admin":
            print("🛑 Refusing to delete admin account")
            return

        # --------------------------------------
        # COMPANY CLEANUP
        # --------------------------------------

        # IMPORTANT:
        # companies.user_id uses ON DELETE SET NULL
        #
        # So deleting users DOES NOT delete companies.
        #
        # We must manually delete company records.
        #
        # Then PostgreSQL CASCADE handles:
        # - internships
        # - applications
        # - external_company_access
        # - internship_stats
        # etc.

        if role == "company":

            cur.execute("""
                SELECT id, name
                FROM companies
                WHERE user_id = %s
            """, (user_id,))

            company = cur.fetchone()

            if company:

                print(f"🏢 Company linked: {company['name']}")

                if not DRY_RUN:

                    cur.execute("""
                        DELETE FROM companies
                        WHERE id = %s
                    """, (company["id"],))

                    print("🗑️ Company deleted")

        # --------------------------------------
        # DELETE USER
        # --------------------------------------

        # PostgreSQL CASCADE automatically deletes:
        #
        # students
        # student_skills
        # experiences
        # applications
        # saved_internships
        # user_files
        # admin_logs
        #
        # etc.

        if DRY_RUN:

            print("🧪 DRY RUN ENABLED")
            print("✅ No real deletion performed")
            return

        cur.execute("""
            DELETE FROM users
            WHERE id = %s
        """, (user_id,))

        print(f"✅ Deleted user: {email}")


# ======================================
# MAIN
# ======================================

if __name__ == "__main__":

    print("🚨 Starting deletion process...\n")

    for email in EMAILS_TO_DELETE:
        delete_user_by_email(email)

    print("\n🎉 Finished")