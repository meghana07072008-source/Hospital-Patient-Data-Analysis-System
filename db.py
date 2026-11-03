"""Small database layer.

MySQL (through PyMySQL) is the primary backend. SQLite is supported as a
zero-setup fallback (DB_BACKEND=sqlite) so the app can be tried or tested
without a MySQL server. All SQL in the project is written with %s
placeholders and plain joins, so it runs unchanged on both.
"""
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import current_app, g, has_request_context, request

SQLITE_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        last_login TEXT NULL)""",
    """CREATE TABLE IF NOT EXISTS departments (
        department_id INTEGER PRIMARY KEY AUTOINCREMENT,
        department_name TEXT NOT NULL UNIQUE)""",
    """CREATE TABLE IF NOT EXISTS patients (
        patient_id INTEGER PRIMARY KEY AUTOINCREMENT,
        age_band TEXT NOT NULL,
        gender TEXT NULL)""",
    """CREATE TABLE IF NOT EXISTS visits (
        visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
        department_id INTEGER NOT NULL REFERENCES departments(department_id),
        visit_date TEXT NOT NULL,
        visit_type TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_visits_date ON visits (visit_date)",
    "CREATE INDEX IF NOT EXISTS idx_visits_department ON visits (department_id)",
    """CREATE TABLE IF NOT EXISTS audit_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NULL,
        action TEXT NOT NULL,
        detail TEXT NULL,
        ip_address TEXT NULL,
        created_at TEXT NOT NULL)""",
]


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Conn:
    """Thin wrapper giving MySQL and SQLite the same small API."""

    def __init__(self, raw, backend):
        self.raw = raw
        self.backend = backend

    def _sql(self, sql):
        return sql.replace("%s", "?") if self.backend == "sqlite" else sql

    def all(self, sql, params=()):
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql, params=(), default=None):
        row = self.one(sql, params)
        if not row:
            return default
        value = next(iter(row.values()))
        return default if value is None else value

    def execute(self, sql, params=()):
        cur = self.raw.cursor()
        try:
            cur.execute(self._sql(sql), tuple(params))
            self.raw.commit()
            return cur.lastrowid
        except Exception:
            self.raw.rollback()
            raise
        finally:
            cur.close()

    def executemany(self, sql, seq, chunk=5000):
        seq = list(seq)
        cur = self.raw.cursor()
        try:
            for i in range(0, len(seq), chunk):
                cur.executemany(self._sql(sql), seq[i:i + chunk])
            self.raw.commit()
        except Exception:
            self.raw.rollback()
            raise
        finally:
            cur.close()

    def close(self):
        try:
            self.raw.close()
        except Exception:
            pass


def connect(cfg):
    backend = cfg["DB_BACKEND"]
    if backend == "sqlite":
        Path(cfg["SQLITE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(cfg["SQLITE_PATH"], check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        return Conn(raw, "sqlite")

    import pymysql  # imported lazily so SQLite mode does not need it

    raw = pymysql.connect(
        host=cfg["MYSQL_HOST"], port=cfg["MYSQL_PORT"],
        user=cfg["MYSQL_USER"], password=cfg["MYSQL_PASSWORD"],
        database=cfg["MYSQL_DB"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, autocommit=False,
    )
    return Conn(raw, "mysql")


def ensure_database(cfg):
    """MySQL only: create the database if the account is allowed to."""
    if cfg["DB_BACKEND"] != "mysql":
        return
    import pymysql

    raw = pymysql.connect(
        host=cfg["MYSQL_HOST"], port=cfg["MYSQL_PORT"],
        user=cfg["MYSQL_USER"], password=cfg["MYSQL_PASSWORD"], charset="utf8mb4",
    )
    try:
        with raw.cursor() as cur:
            name = cfg["MYSQL_DB"].replace("`", "")
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        raw.commit()
    finally:
        raw.close()


def init_schema(db, cfg):
    if cfg["DB_BACKEND"] == "sqlite":
        for stmt in SQLITE_SCHEMA:
            db.execute(stmt)
        return
    text = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    text = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    for stmt in (s.strip() for s in text.split(";")):
        if not stmt or re.match(r"(?is)^(create database|use)\b", stmt):
            continue
        db.execute(stmt)


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config)
        if g.db.backend == "mysql":
            g.db.raw.ping(reconnect=True)
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def log_action(action, detail=None, user_id=None):
    """Write an audit-trail row (who did what). Never raises."""
    try:
        db = get_db()
        uid = user_id if user_id is not None else (g.user["user_id"] if getattr(g, "user", None) else None)
        ip = request.remote_addr if has_request_context() else None
        db.execute(
            "INSERT INTO audit_log (user_id, action, detail, ip_address, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (uid, action, (detail or "")[:250], ip, now_str()),
        )
    except Exception:
        pass
