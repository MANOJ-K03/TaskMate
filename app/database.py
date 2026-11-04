"""SQLite connection helpers. All SQL for the app goes through connections made here."""
import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"
# Tests change this to a temporary file; normal runs use taskmate.db in the project folder.
DB_PATH = Path(os.environ.get("TASKMATE_DB", BASE_DIR / "taskmate.db"))


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite leaves this OFF by default
    return conn


def init_db() -> None:
    """Create tables, indexes and starter categories if they do not exist yet."""
    conn = connect()
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def get_db():
    """FastAPI dependency: one connection per request, always closed."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
