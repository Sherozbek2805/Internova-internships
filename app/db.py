import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import closing


DATABASE_URL = os.getenv("DATABASE_URL")


def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode = "require", connect_timeout = 5)
    return conn


def get_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)


def init_db():
    with closing(get_db()) as conn:
        cur = conn.cursor()

        # USERS
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('student','company','admin')),
            school TEXT,
            skills TEXT,
            verified BOOLEAN DEFAULT FALSE,
            banned BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cv_path TEXT
        )
        """)

        # COMPANIES
        cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            website TEXT,
            description TEXT,
            logo_url TEXT,
            verified BOOLEAN DEFAULT FALSE,
            phone1 TEXT,
            phone2 TEXT,
            address TEXT,
            industry TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)

        # INTERNSHIPS
        cur.execute("""
        CREATE TABLE IF NOT EXISTS internships (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT,
            duration TEXT,
            deadline TEXT,
            stipend TEXT,
            skills TEXT,
            internship_type TEXT,
            approved BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
        )
        """)

        # APPLICATIONS
        cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            internship_id INTEGER NOT NULL,
            status TEXT DEFAULT 'Yangi',
            score INTEGER DEFAULT 0 CHECK(score >= 0 AND score <= 100),
            evaluation_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, internship_id),
            FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (internship_id) REFERENCES internships(id) ON DELETE CASCADE
        )
        """)

        # ANALYTICS
        cur.execute("""
        CREATE TABLE IF NOT EXISTS analytics (
            id SERIAL PRIMARY KEY,
            internship_id INTEGER UNIQUE NOT NULL,
            views INTEGER DEFAULT 0,
            applications INTEGER DEFAULT 0,
            FOREIGN KEY (internship_id) REFERENCES internships(id) ON DELETE CASCADE
        )
        """)

        # SAVED INTERNSHIPS
        cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_internships (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            internship_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, internship_id),
            FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (internship_id) REFERENCES internships(id) ON DELETE CASCADE
        )
        """)

        # ADMIN LOGS
        cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id SERIAL PRIMARY KEY,
            admin_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)

        conn.commit()