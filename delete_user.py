import os
import psycopg2


def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    return psycopg2.connect(database_url)


def delete_users_by_email(emails):
    conn = get_connection()
    cur = conn.cursor()

    try:
        for email in emails:
            cur.execute("DELETE FROM users WHERE email = %s RETURNING id;", (email,))
            result = cur.fetchone()

            if result:
                print(f"✅ Deleted user: {email} (id={result[0]})")
            else:
                print(f"⚠️ User not found: {email}")

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("❌ Error occurred:", str(e))

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    # 🔥 Put emails you want to delete here
    USERS_TO_DELETE = [
        "sherozbek316@gmail.com",
        "moviyonteam@gmail.com"
    ]

    print("Starting deletion...\n")
    delete_users_by_email(USERS_TO_DELETE)
    print("\nDone.")