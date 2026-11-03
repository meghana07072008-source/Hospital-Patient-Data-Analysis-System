"""Application configuration.

Values come from environment variables. For local use, copy `.env.example`
to `.env` and edit it - the file is read automatically on start-up.
"""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv():
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key-before-sharing")

    # "mysql" (default) or "sqlite" (zero-setup fallback for quick demos/tests)
    DB_BACKEND = os.environ.get("DB_BACKEND", "mysql").lower()
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
    MYSQL_DB = os.environ.get("MYSQL_DB", "hospital_analytics")
    SQLITE_PATH = os.environ.get("SQLITE_PATH", str(BASE_DIR / "instance" / "hospital.db"))

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Seed accounts (change these before sharing the app with anyone)
    ADMIN_NAME = os.environ.get("ADMIN_NAME", "Hospital Admin")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@hospital.local")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@12345")
    DEMO_USER_EMAIL = os.environ.get("DEMO_USER_EMAIL", "user@hospital.local")
    DEMO_USER_PASSWORD = os.environ.get("DEMO_USER_PASSWORD", "User@12345")
    SHOW_DEMO_HINT = os.environ.get("SHOW_DEMO_HINT", "1") == "1"

    # Aggregated tables hide any cell with fewer visits than this
    MIN_CELL = 5

    DISCLAIMER = (
        "Operational statistics from synthetic data. "
        "Not clinical advice, diagnosis or treatment guidance."
    )
