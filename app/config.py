import os
from pathlib import Path
from datetime import timedelta


BASE_DIR = Path(__file__).resolve().parent.parent


def _get_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

    PREFERRED_URL_SCHEME = os.getenv("PREFERRED_URL_SCHEME", "https")

    SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "internova_session")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = _get_bool("SESSION_COOKIE_SECURE", True)
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_PERMANENT = False
    SESSION_REFRESH_EACH_REQUEST = False
    PERMANENT_SESSION_LIFETIME = timedelta(
        seconds=int(os.getenv("PERMANENT_SESSION_LIFETIME", 3600))
    )

    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = _get_bool("REMEMBER_COOKIE_SECURE", True)
    REMEMBER_COOKIE_SAMESITE = os.getenv("REMEMBER_COOKIE_SAMESITE", "Lax")

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    WTF_CSRF_HEADERS = ["X-CSRFToken", "X-CSRF-Token"]

    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))

    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = _get_bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL = _get_bool("MAIL_USE_SSL", False)
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", MAIL_USERNAME)

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    DATABASE_URL = os.getenv("DATABASE_URL")

    if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")

    EMAIL_TOKEN_EXPIRES_SECONDS = int(os.getenv("EMAIL_TOKEN_EXPIRES_SECONDS", 3600))
    RESET_TOKEN_EXPIRES_SECONDS = int(os.getenv("RESET_TOKEN_EXPIRES_SECONDS", 1800))

    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "200 per day; 50 per hour")
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")

    ADMIN_ALLOWED_IPS = [
        ip.strip() for ip in os.getenv("ADMIN_ALLOWED_IPS", "").split(",") if ip.strip()
    ]

    @staticmethod
    def validate():
        required = ["SECRET_KEY", "JWT_SECRET_KEY"]
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}"
            )