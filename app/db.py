"""
db.py — Database connection pool + idempotent schema init.

Design rules (critical for Render safety):
  - Every statement must be idempotent: safe to run on every cold start.
  - Use CREATE TABLE IF NOT EXISTS, ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS.
  - Wrap constraint/type creation in DO $$ EXCEPTION WHEN duplicate_object blocks.
  - Never DROP or alter column types without an explicit migration strategy.
  - ALTER COLUMN DROP NOT NULL is always safe to repeat.
"""

import os
import time
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# ─────────────────────────────────────────────
# Connection pool — ThreadedConnectionPool is
# safe under Gunicorn/gevent worker models.
# ─────────────────────────────────────────────
_pool: ThreadedConnectionPool | None = None


def _build_pool(retries: int = 5, delay: float = 2.0) -> ThreadedConnectionPool:
    """Create the pool, retrying on connection failure (Render cold-start lag)."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            p = ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=DATABASE_URL,
                sslmode="require",
            )
            log.info("DB pool created on attempt %d", attempt)
            return p
        except Exception as exc:
            last_err = exc
            log.warning("DB pool attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError(f"Could not connect to the database after {retries} tries: {last_err}")


def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = _build_pool()
    return _pool


def get_db():
    return get_pool().getconn()


def release_db(conn):
    get_pool().putconn(conn)


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
        try:
            cur.close()
        except Exception:
            pass
        release_db(conn)


# ─────────────────────────────────────────────
# Schema init — called once per process start.
# Every statement MUST be idempotent.
# ─────────────────────────────────────────────
def init_db():
    with get_cursor() as cur:

        # ── APPLICATION STATUS ENUM ──────────────────────────────────────────
        # Must exist before the applications table is created.
        cur.execute("""
        DO $$ BEGIN
            CREATE TYPE application_status AS ENUM
                ('new','reviewing','shortlisted','accepted','rejected');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)

        # ── USERS ────────────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          SERIAL PRIMARY KEY,
            name        TEXT    NOT NULL,
            email       TEXT    UNIQUE NOT NULL,
            password    TEXT,                        -- nullable: Google OAuth users have no password
            role        TEXT    CHECK (role IN ('student','company','admin')),
            verified    BOOLEAN DEFAULT FALSE,
            banned      BOOLEAN DEFAULT FALSE,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Safety: if table was created with NOT NULL, relax it now.
        cur.execute("ALTER TABLE users ALTER COLUMN password DROP NOT NULL;")

        # ── STUDENTS ─────────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            phone      TEXT,
            telegram   TEXT,
            location   TEXT,
            school     TEXT,
            grade      TEXT,
            linkedin   TEXT,
            github     TEXT,
            bio        TEXT,
            program    TEXT,
            gpa        DECIMAL(3,2),
            subjects   TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Guard: add columns that may be missing in older deploys
        for col, typedef in [
            ("program",  "TEXT"),
            ("gpa",      "DECIMAL(3,2)"),
            ("subjects", "TEXT"),
        ]:
            cur.execute(f"ALTER TABLE students ADD COLUMN IF NOT EXISTS {col} {typedef};")

        # ── COMPANIES ────────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id             SERIAL PRIMARY KEY,
            user_id        INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
            name           TEXT NOT NULL,
            email          TEXT,
            phone1         TEXT,
            phone2         TEXT,
            website        TEXT,
            description    TEXT,
            logo_url       TEXT,
            industry       TEXT,
            verified       BOOLEAN DEFAULT FALSE,
            address        TEXT,
            public_visible BOOLEAN DEFAULT TRUE,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        for col, typedef in [
            ("email",          "TEXT"),
            ("public_visible", "BOOLEAN DEFAULT TRUE"),
        ]:
            cur.execute(f"ALTER TABLE companies ADD COLUMN IF NOT EXISTS {col} {typedef};")

        # Ensure the FK allows SET NULL on user delete
        cur.execute("""
        DO $$ BEGIN
            ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_user_id_fkey;
            ALTER TABLE companies
                ADD CONSTRAINT companies_user_id_fkey
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)

        # ── SKILLS ───────────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            id   SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS student_skills (
            student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
            skill_id   INTEGER REFERENCES skills(id)   ON DELETE CASCADE,
            PRIMARY KEY (student_id, skill_id)
        )
        """)

        # ── INTERNSHIPS ──────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS internships (
            id               SERIAL PRIMARY KEY,
            company_id       INTEGER REFERENCES companies(id) ON DELETE CASCADE,
            title            TEXT NOT NULL,
            description      TEXT,
            location         TEXT,
            duration         TEXT,
            deadline         DATE,
            stipend          INTEGER,
            type             TEXT,
            approved         BOOLEAN DEFAULT FALSE,
            source_type      TEXT CHECK (source_type IN ('company','admin')) DEFAULT 'company',
            created_by_admin INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        for col, typedef in [
            ("source_type",      "TEXT CHECK (source_type IN ('company','admin')) DEFAULT 'company'"),
            ("created_by_admin", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
        ]:
            cur.execute(f"ALTER TABLE internships ADD COLUMN IF NOT EXISTS {col} {typedef};")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS internship_skills (
            internship_id INTEGER REFERENCES internships(id) ON DELETE CASCADE,
            skill_id      INTEGER REFERENCES skills(id)      ON DELETE CASCADE,
            PRIMARY KEY (internship_id, skill_id)
        )
        """)

        # ── APPLICATIONS ─────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id                SERIAL PRIMARY KEY,
            student_id        INTEGER REFERENCES students(id)    ON DELETE CASCADE,
            internship_id     INTEGER REFERENCES internships(id) ON DELETE CASCADE,
            company_id        INTEGER REFERENCES companies(id)   ON DELETE CASCADE,
            status            application_status DEFAULT 'new',
            score             INTEGER DEFAULT 0 CHECK (score >= 0 AND score <= 100),
            evaluation_note   TEXT,
            motivation        TEXT,
            scored_by         INTEGER REFERENCES users(id),
            score_updated_at  TIMESTAMP,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (student_id, internship_id)
        )
        """)

        # Trigger: auto-fill company_id from internship
        cur.execute("""
        CREATE OR REPLACE FUNCTION set_application_company()
        RETURNS TRIGGER AS $$
        BEGIN
            SELECT company_id INTO NEW.company_id
            FROM internships WHERE id = NEW.internship_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)
        cur.execute("DROP TRIGGER IF EXISTS trg_set_company ON applications;")
        cur.execute("""
        CREATE TRIGGER trg_set_company
        BEFORE INSERT ON applications
        FOR EACH ROW EXECUTE FUNCTION set_application_company();
        """)

        # Trigger: auto-update updated_at
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
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
        """)

        # ── SAVED INTERNSHIPS ────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_internships (
            student_id    INTEGER REFERENCES students(id)    ON DELETE CASCADE,
            internship_id INTEGER REFERENCES internships(id) ON DELETE CASCADE,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (student_id, internship_id)
        )
        """)

        # ── EXPERIENCES ──────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS experiences (
            id           SERIAL PRIMARY KEY,
            student_id   INTEGER REFERENCES students(id) ON DELETE CASCADE,
            title        TEXT,
            organization TEXT,
            role         TEXT,
            description  TEXT,
            grade_levels JSONB,
            start_date   DATE,
            end_date     DATE,
            is_current   BOOLEAN DEFAULT FALSE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        for col, typedef in [
            ("role",         "TEXT"),
            ("grade_levels", "JSONB"),
        ]:
            cur.execute(f"ALTER TABLE experiences ADD COLUMN IF NOT EXISTS {col} {typedef};")

        # ── USER FILES ───────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_files (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
            file_url   TEXT,
            file_type  TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cur.execute("""
        DO $$ BEGIN
            ALTER TABLE user_files
                ADD CONSTRAINT file_type_check
                CHECK (file_type IN ('cv','certificate','other'));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)

        # ── INTERNSHIP STATS ─────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS internship_stats (
            internship_id INTEGER PRIMARY KEY REFERENCES internships(id) ON DELETE CASCADE,
            views         INTEGER DEFAULT 0,
            applications  INTEGER DEFAULT 0
        )
        """)

        # ── EXTERNAL COMPANY ACCESS ──────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS external_company_access (
            id               SERIAL PRIMARY KEY,
            company_id       INTEGER REFERENCES companies(id) ON DELETE CASCADE,
            access_code      TEXT UNIQUE NOT NULL,
            is_active        BOOLEAN DEFAULT TRUE,
            expires_at       TIMESTAMP,
            created_by_admin INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # ── ADMIN LOGS ───────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id            SERIAL PRIMARY KEY,
            admin_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            action        TEXT NOT NULL,
            target_type   TEXT,
            target_id     INTEGER,
            details       TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # ── WAITLIST ─────────────────────────────────────────────────────────
        cur.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id         SERIAL PRIMARY KEY,
            name       TEXT NOT NULL,
            email      TEXT UNIQUE NOT NULL,
            role       TEXT DEFAULT 'student',
            school_or_company TEXT,
            grade      TEXT,
            field      TEXT,
            goals      TEXT,
            phone      TEXT,
            telegram   TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        for col, typedef in [
            ("role",              "TEXT DEFAULT 'student'"),
            ("school_or_company", "TEXT"),
            ("grade",             "TEXT"),
            ("field",             "TEXT"),
            ("goals",             "TEXT"),
        ]:
            cur.execute(f"ALTER TABLE waitlist ADD COLUMN IF NOT EXISTS {col} {typedef};")

        # ── INDEXES ──────────────────────────────────────────────────────────
        # Unique indexes (case-insensitive email lookups)
        for name, definition in [
            ("idx_users_email_lower",    "users (LOWER(email))"),
            ("idx_waitlist_email_lower", "waitlist (LOWER(email))"),
            ("idx_external_company_code","external_company_access (access_code)"),
        ]:
            cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {definition};")

        # Regular performance indexes
        for name, definition in [
            ("idx_app_status",              "applications (status)"),
            ("idx_app_score",               "applications (score)"),
            ("idx_app_company",             "applications (company_id)"),
            ("idx_app_student",             "applications (student_id)"),
            ("idx_app_internship",          "applications (internship_id)"),
            ("idx_internships_company",     "internships (company_id)"),
            ("idx_internships_approved",    "internships (approved)"),
            ("idx_internships_source_type", "internships (source_type)"),
            ("idx_saved_student",           "saved_internships (student_id)"),
        ]:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {definition};")

    log.info("Database schema initialised successfully.")
