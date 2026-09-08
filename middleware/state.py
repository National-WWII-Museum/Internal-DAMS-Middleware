"""
state.py
Persistence for the poll watermark (dbo.sync_state) and the landing table
(dbo.emu_staging), both in the remote MS SQL Server database - connection
details in config.py / .env.

The schema is owned and provisioned by the DBA (see the project's SQL
script). This module only reads and writes rows; it never creates or
alters tables.
"""
from datetime import date, datetime

import pyodbc

from .config import DB_CONNECTION_STRING
from .mapping import WRITE_COLUMNS

# dbo.sync_state holds exactly one row, updated in place.
SYNC_STATE_ID = 1
DEFAULT_SYNC_DATE = "2026-03-01"


def get_connection():
    return pyodbc.connect(DB_CONNECTION_STRING)


# --- sync_state -------------------------------------------------------------

def get_last_sync_date(conn, default=DEFAULT_SYNC_DATE):
    """The 'gte' watermark for the next poll, as a 'YYYY-MM-DD' string.

    Reads dbo.sync_state.last_sync_date (row id=1); falls back to `default`
    when that row is missing or the column is NULL.
    """
    row = conn.execute(
        "SELECT last_sync_date FROM sync_state WHERE id = ?", (SYNC_STATE_ID,)
    ).fetchone()
    if row and row[0] is not None:
        value = row[0]
        if isinstance(value, (datetime, date)):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]
    return default


def has_synced_before(conn):
    """True once a real run has written a watermark - i.e. get_last_sync_date()
    is returning a prior run's date rather than its hardcoded default."""
    row = conn.execute(
        "SELECT last_sync_date FROM sync_state WHERE id = ?", (SYNC_STATE_ID,)
    ).fetchone()
    return bool(row and row[0] is not None)


_SYNC_STATE_MERGE = """
MERGE dbo.sync_state AS t
USING (SELECT ? AS id) AS s
  ON t.id = s.id
WHEN MATCHED THEN UPDATE SET
    last_sync_date = ?, last_run_at = ?, rows_processed = ?, notes = ?
WHEN NOT MATCHED THEN
    INSERT (id, last_sync_date, last_run_at, rows_processed, notes)
    VALUES (?, ?, ?, ?, ?);
"""


def update_sync_state(conn, last_sync_date, last_run_at, rows_processed, notes=None):
    """Write the single sync_state row. `last_sync_date` may be a
    'YYYY-MM-DD' string or a date/datetime; `notes` is truncated to the
    column's 1000 chars."""
    if isinstance(last_sync_date, str):
        last_sync_date = datetime.strptime(last_sync_date, "%Y-%m-%d").date()
    if notes is not None:
        notes = str(notes)[:1000]
    params = [
        SYNC_STATE_ID, last_sync_date, last_run_at, rows_processed, notes,
        SYNC_STATE_ID, last_sync_date, last_run_at, rows_processed, notes,
    ]
    conn.execute(_SYNC_STATE_MERGE, params)
    conn.commit()


# --- emu_staging -----------------------------------------------------------

_UPDATE_SET = ",\n    ".join(f"{c} = ?" for c in WRITE_COLUMNS)
_INSERT_COLS = ", ".join(["irn", *WRITE_COLUMNS])
_INSERT_PLACEHOLDERS = ", ".join(["?"] * (1 + len(WRITE_COLUMNS)))

_STAGING_MERGE = f"""
MERGE dbo.emu_staging AS t
USING (SELECT ? AS irn) AS s
  ON t.irn = s.irn
WHEN MATCHED THEN UPDATE SET
    {_UPDATE_SET},
    synced = 0,
    sync_failed = 0,
    updated_at = SYSUTCDATETIME()
WHEN NOT MATCHED THEN
    INSERT ({_INSERT_COLS})
    VALUES ({_INSERT_PLACEHOLDERS});
"""


def upsert_staging_record(conn, irn, row):
    """Insert or update one emu_staging row, keyed on irn.

    An existing row is overwritten and its synced / sync_failed flags reset
    to 0 so the NetX push step re-processes the changed record. Commits per
    record so a mid-run failure still leaves already-staged rows behind.
    """
    values = [row[c] for c in WRITE_COLUMNS]
    conn.execute(_STAGING_MERGE, [irn, *values, irn, *values])
    conn.commit()
