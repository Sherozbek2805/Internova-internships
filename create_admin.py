# create_admin.py

from werkzeug.security import generate_password_hash
from app import create_app
from app.db import get_cursor

ADMIN_NAME = "Sherozbek Uktamov"
ADMIN_EMAIL = "uksherozbek@gmail.com"
ADMIN_PASSWORD = "Qazwsx$$111"
ADMIN_ROLE = "admin"


def create_admin():
    app = create_app()

    with app.app_context():
        try:
            with get_cursor() as cur:

                # Check existing admin
                cur.execute("""
                    SELECT id FROM users
                    WHERE LOWER(email) = LOWER(%s)
                """, (ADMIN_EMAIL,))

                existing = cur.fetchone()

                if existing:
                    print("Admin already exists.")
                    return

                hashed_password = generate_password_hash(ADMIN_PASSWORD)

                # Create admin user
                cur.execute("""
                    INSERT INTO users (
                        name,
                        email,
                        password,
                        role,
                        verified,
                        banned
                    )
                    VALUES (%s, %s, %s, %s, TRUE, FALSE)
                    RETURNING id
                """, (
                    ADMIN_NAME,
                    ADMIN_EMAIL,
                    hashed_password,
                    ADMIN_ROLE
                ))

                admin_id = cur.fetchone()["id"]

                print(f"Admin created successfully. ID: {admin_id}")

        except Exception as e:
            print("CREATE ADMIN ERROR:", e)


if __name__ == "__main__":
    create_admin()