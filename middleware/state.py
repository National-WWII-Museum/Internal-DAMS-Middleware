import sqlite3
from pathlib import Path

# DB Lives in data/, per the folder structure
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sync_state.db"


def get_connection():
    DB_PATH.parent.mkdir(exist_ok=True)  # make sure data/ exists
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create tables if they don't already exist. Safe to call every run."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                module TEXT PRIMARY KEY,
                last_sync_date TEXT,
                last_run_at TEXT,
                last_run_status TEXT,
                last_error TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS synced_records (
                module TEXT,
                irn TEXT,
                date_modified TEXT,
                synced_at TEXT,
                PRIMARY KEY (module, irn, date_modified)
            )
        """)
        conn.commit()
    finally:
        conn.close()

def get_last_sync_date(module, default="2026-01-01"):
    """Returns the date to use as the next 'gte' filter for this module."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT last_sync_date FROM sync_state WHERE module = ?", (module,)
        ).fetchone()
        return row[0] if row else default
    finally:
        conn.close()


def get_synced_irns_for_date(module, date_modified):
    """Returns the set of IRNs already synced for this exact date - used to
    filter out duplicates when polling more than once on the same day."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT irn FROM synced_records WHERE module = ? AND date_modified = ?",
            (module, date_modified),
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def mark_synced(module, irn, date_modified, synced_at):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO synced_records (module, irn, date_modified, synced_at)
               VALUES (?, ?, ?, ?)""",
            (module, irn, date_modified, synced_at),
        )
        conn.commit()
    finally:
        conn.close()


def update_last_sync_date(module, sync_date, run_at, status="success", error=None):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sync_state
               (module, last_sync_date, last_run_at, last_run_status, last_error)
               VALUES (?, ?, ?, ?, ?)""",
            (module, sync_date, run_at, status, error),
        )
        conn.commit()
    finally:
        conn.close()