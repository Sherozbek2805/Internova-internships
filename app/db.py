import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager

# 🔐 ENV CHECK
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

# ⚡ CONNECTION POOL
pool = SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    dsn=DATABASE_URL,
    sslmode="require"
)

# 🔄 GET CONNECTION
def get_db():
    return pool.getconn()

# 🔄 RELEASE CONNECTION
def release_db(conn):
    pool.putconn(conn)

# 🎯 CONTEXT MANAGER
@contextmanager
def get_cursor():
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        release_db(conn)

# 🧱 INIT DB (REDESIGNED)
def init_db():
    with get_cursor() as cur:

        # =========================
        # USERS (AUTH)
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT CHECK (role IN ('student','company','admin')),
            verified BOOLEAN DEFAULT FALSE,
            banned BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # =========================
        # STUDENTS (NEW)
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            phone TEXT,
            telegram TEXT,
            location TEXT,
            school TEXT,
            grade TEXT,
            linkedin TEXT,
            github TEXT,
            bio TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # =========================
        # COMPANIES
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            phone1 TEXT,
            phone2 TEXT,
            website TEXT,
            description TEXT,
            logo_url TEXT,
            industry TEXT,
            verified BOOLEAN DEFAULT FALSE,
            address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # =========================
        # SKILLS (NORMALIZED)
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
        """)

        # =========================
        # STUDENT SKILLS
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS student_skills (
            student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
            skill_id INTEGER REFERENCES skills(id) ON DELETE CASCADE,
            PRIMARY KEY (student_id, skill_id)
        )
        """)

        # =========================
        # INTERNSHIPS
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS internships (
            id SERIAL PRIMARY KEY,
            company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            location TEXT,
            duration TEXT,
            deadline DATE,
            stipend INTEGER,
            type TEXT,
            approved BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # =========================
        # INTERNSHIP SKILLS
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS internship_skills (
            internship_id INTEGER REFERENCES internships(id) ON DELETE CASCADE,
            skill_id INTEGER REFERENCES skills(id) ON DELETE CASCADE,
            PRIMARY KEY (internship_id, skill_id)
        )
        """)

        # =========================
        # APPLICATION STATUS ENUM
        # =========================
        cur.execute("""
        DO $$ BEGIN
            CREATE TYPE application_status AS ENUM 
            ('new','reviewing','shortlisted','accepted','rejected');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """)

        # =========================
        # APPLICATIONS (FIXED 🔥)
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id SERIAL PRIMARY KEY,
            student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
            internship_id INTEGER REFERENCES internships(id) ON DELETE CASCADE,
            company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,

            status application_status DEFAULT 'new',
            score INTEGER DEFAULT 0 CHECK(score >= 0 AND score <= 100),
            evaluation_note TEXT,
            motivation TEXT,

            scored_by INTEGER REFERENCES users(id),
            score_updated_at TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(student_id, internship_id)
        )
        """)

        cur.execute("""
        CREATE OR REPLACE FUNCTION set_application_company()
        RETURNS TRIGGER AS $$
        BEGIN
            SELECT company_id INTO NEW.company_id
            FROM internships
            WHERE id = NEW.internship_id;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)

        cur.execute("""
        DROP TRIGGER IF EXISTS trg_set_company ON applications;
        """)

        cur.execute("""
        CREATE TRIGGER trg_set_company
        BEFORE INSERT ON applications
        FOR EACH ROW
        EXECUTE FUNCTION set_application_company();
        """)

        # =========================
        # SAVED INTERNSHIPS
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_internships (
            student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
            internship_id INTEGER REFERENCES internships(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (student_id, internship_id)
        )
        """)

        # =========================
        # EXPERIENCES
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS experiences (
            id SERIAL PRIMARY KEY,
            student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
            title TEXT,
            organization TEXT,
            description TEXT,
            start_date DATE,
            end_date DATE,
            is_current BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # =========================
        # FILES (CV, CERTIFICATES)
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_files (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            file_url TEXT,
            file_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # =========================
        # ANALYTICS
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS internship_stats (
            internship_id INTEGER PRIMARY KEY REFERENCES internships(id) ON DELETE CASCADE,
            views INTEGER DEFAULT 0,
            applications INTEGER DEFAULT 0
        )
        """)

        # =========================
        # ADMIN LOGS
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id SERIAL PRIMARY KEY,
            admin_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # =========================
        # 🔥 FINAL PRODUCTION UPGRADES
        # =========================

        # 1. AUTO SET company_id (CRITICAL)
        cur.execute("""
        CREATE OR REPLACE FUNCTION set_application_company()
        RETURNS TRIGGER AS $$
        BEGIN
            SELECT company_id INTO NEW.company_id
            FROM internships
            WHERE id = NEW.internship_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)

        cur.execute("DROP TRIGGER IF EXISTS trg_set_company ON applications;")

        cur.execute("""
        CREATE TRIGGER trg_set_company
        BEFORE INSERT ON applications
        FOR EACH ROW
        EXECUTE FUNCTION set_application_company();
        """)

        # 2. AUTO UPDATE updated_at
        cur.execute("""
        CREATE OR REPLACE FUNCTION update_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)

        cur.execute("DROP TRIGGER IF EXISTS trg_update_applications ON applications;")

        cur.execute("""
        CREATE TRIGGER trg_update_applications
        BEFORE UPDATE ON applications
        FOR EACH ROW
        EXECUTE FUNCTION update_timestamp();
        """)

        # 3. CASE-INSENSITIVE EMAIL
        cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower
        ON users (LOWER(email));
        """)

        # 4. PERFORMANCE INDEXES
        cur.execute("CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_app_score ON applications(score)")

        # 5. FILE TYPE SAFETY
        cur.execute("""
        DO $$ BEGIN
            ALTER TABLE user_files
            ADD CONSTRAINT file_type_check
            CHECK (file_type IN ('cv','certificate','other'));
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """)

        # =========================
        # WAITLIST
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            telegram TEXT,
            school TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_waitlist_email_lower
        ON waitlist (LOWER(email));
        """)

        # =========================
        # ⚡ INDEXES (CRITICAL)
        # =========================
        cur.execute("CREATE INDEX IF NOT EXISTS idx_app_company ON applications(company_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_app_student ON applications(student_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_app_internship ON applications(internship_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_internships_company ON internships(company_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")