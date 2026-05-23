from app.db import get_cursor

COMPANIES_TO_DELETE = [
    "Tester"
]

DRY_RUN = False


def delete_company_only(company_name):

    with get_cursor() as cur:

        # FIND COMPANY
        cur.execute("""
            SELECT id, name, user_id
            FROM companies
            WHERE LOWER(name)=LOWER(%s)
        """, (company_name,))

        company = cur.fetchone()

        if not company:
            print(f"❌ Company not found: {company_name}")
            return

        print(f"\n⚠️ Found company:")
        print(f"   Name    : {company['name']}")
        print(f"   ID      : {company['id']}")
        print(f"   User ID : {company['user_id']}")

        if DRY_RUN:
            print("🧪 DRY RUN ENABLED")
            print("✅ No deletion performed")
            return

        # DELETE ONLY COMPANY
        cur.execute("""
            DELETE FROM companies
            WHERE id=%s
        """, (company["id"],))

        print(f"✅ Deleted company: {company['name']}")
        print("👤 User account preserved")


if __name__ == "__main__":

    for company_name in COMPANIES_TO_DELETE:
        delete_company_only(company_name)