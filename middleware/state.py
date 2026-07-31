import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

# DB Lives in data/, per the folder structure
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sync_state.db"


def get_connection():
    DB_PATH.parent.mkdir(exist_ok=True)  # make sure data/ exists
    return sqlite3.connect(DB_PATH)


def init_db(conn):
    """Create tables if they don't already exist. Safe to call every run."""
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS netx_queue (
            irn INTEGER NOT NULL,
            module TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            retry_count INTEGER NOT NULL DEFAULT 0,
            queued_at TEXT NOT NULL,
            sent_at TEXT,
            last_error TEXT,
            PRIMARY KEY (irn, module)
        )
    """)
    conn.commit()


def get_last_sync_date(conn, module, default="2026-01-01"):
    """Returns the date to use as the next 'gte' filter for this module."""
    row = conn.execute(
        "SELECT last_sync_date FROM sync_state WHERE module = ?", (module,)
    ).fetchone()
    return row[0] if row else default


def get_synced_irns_for_date(conn, module, date_modified):
    """Returns the set of IRNs already synced for this exact date - used to
    filter out duplicates when polling more than once on the same day."""
    rows = conn.execute(
        "SELECT irn FROM synced_records WHERE module = ? AND date_modified = ?",
        (module, date_modified),
    ).fetchall()
    return {row[0] for row in rows}


def mark_synced(conn, module, irn, date_modified, synced_at):
    conn.execute(
        """INSERT OR REPLACE INTO synced_records (module, irn, date_modified, synced_at)
           VALUES (?, ?, ?, ?)""",
        (module, irn, date_modified, synced_at),
    )
    conn.commit()


def queue_for_netx(conn, module, irn, payload, queued_at, status="pending"):
    """Stage one fetched record for the separate NetX-insert task.

    One row per (module, irn) - re-queuing an irn that's already pending
    (e.g. re-fetched on a later poll before NetX has consumed it) overwrites
    the payload and resets it to pending rather than piling up duplicates.
    """
    conn.execute(
        """INSERT OR REPLACE INTO netx_queue
           (irn, module, payload, status, retry_count, queued_at, sent_at, last_error)
           VALUES (?, ?, ?, ?, 0, ?, NULL, NULL)""",
        (irn, module, payload, status, queued_at),
    )
    conn.commit()


def update_last_sync_date(conn, module, sync_date, run_at, status="success", error=None):
    conn.execute(
        """INSERT OR REPLACE INTO sync_state
           (module, last_sync_date, last_run_at, last_run_status, last_error)
           VALUES (?, ?, ?, ?, ?)""",
        (module, sync_date, run_at, status, error),
    )
    conn.commit()


def cleanup_sent_netx_records(conn, module=None):
    """
    Delete netx_queue rows already marked 'sent' - once a record has
    been exported/handed off there's no further use for the row, so
    this keeps the table from growing unbounded run over run.
    """
    if module is not None:
        cursor = conn.execute(
            "DELETE FROM netx_queue WHERE status = 'sent' AND module = ?", (module,)
        )
    else:
        cursor = conn.execute("DELETE FROM netx_queue WHERE status = 'sent'")
    conn.commit()
    return cursor.rowcount


def cleanup_old_synced_records(conn, days_to_keep=7):
    """
    Delete synced_records rows older than the retention window.

    synced_records only exists to dedupe against same-day re-processing
    caused by AdmDateModified being date-only (no time component). Once
    a date is more than a day or two in the past, last_sync_date will
    never generate a query range that reaches back that far again, so
    old rows serve no purpose and just grow the DB unbounded.
    """
    cutoff = (datetime.now() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
    cursor = conn.execute(
        "DELETE FROM synced_records WHERE date_modified < ?", (cutoff,)
    )
    conn.commit()
    return cursor.rowcount