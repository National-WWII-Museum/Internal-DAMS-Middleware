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

# dbo.sync_state is an append-only run log: every run inserts a new row
# (id = MAX(id) + 1) and the newest row carries the current watermark.
DEFAULT_SYNC_DATE = "2026-03-01"


def get_connection():
    return pyodbc.connect(DB_CONNECTION_STRING)


# --- sync_state -------------------------------------------------------------

_LATEST_SYNC_DATE = "SELECT TOP 1 last_sync_date FROM dbo.sync_state ORDER BY id DESC"


def get_last_sync_date(conn, default=DEFAULT_SYNC_DATE):
    """The 'gte' watermark for the next poll, as a 'YYYY-MM-DD' string.

    Reads last_sync_date from the newest dbo.sync_state row (highest id);
    falls back to `default` when the table is empty or the column is NULL.
    """
    row = conn.execute(_LATEST_SYNC_DATE).fetchone()
    if row and row[0] is not None:
        value = row[0]
        if isinstance(value, (datetime, date)):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]
    return default


def has_synced_before(conn):
    """True once a real run has written a watermark - i.e. get_last_sync_date()
    is returning a prior run's date rather than its hardcoded default."""
    row = conn.execute(_LATEST_SYNC_DATE).fetchone()
    return bool(row and row[0] is not None)


# UPDLOCK/HOLDLOCK serialises concurrent runs so two can't pick the same id.
_SYNC_STATE_INSERT = """
INSERT INTO dbo.sync_state (id, last_sync_date, last_run_at, rows_processed, notes)
SELECT COALESCE(MAX(id), 0) + 1, ?, ?, ?, ?
FROM dbo.sync_state WITH (UPDLOCK, HOLDLOCK);
"""


def update_sync_state(conn, last_sync_date, last_run_at, rows_processed, notes=None):
    """Append a new sync_state row for this run. `last_sync_date` may be a
    'YYYY-MM-DD' string or a date/datetime; `notes` is truncated to the
    column's 1000 chars."""
    if isinstance(last_sync_date, str):
        last_sync_date = datetime.strptime(last_sync_date, "%Y-%m-%d").date()
    if notes is not None:
        notes = str(notes)[:1000]
    conn.execute(
        _SYNC_STATE_INSERT, [last_sync_date, last_run_at, rows_processed, notes]
    )
    conn.commit()


# --- emu_staging -----------------------------------------------------------

_UPDATE_SET = ",\n    ".join(f"{c} = ?" for c in WRITE_COLUMNS)
# Every upsert (re)queues the row as 'pending'; routing.py then flips it to
# 'ready' or 'holding'. status is bookkeeping, so it is not in WRITE_COLUMNS.
_INSERT_COLS = ", ".join(["irn", *WRITE_COLUMNS, "status"])
_INSERT_PLACEHOLDERS = ", ".join(["?"] * (1 + len(WRITE_COLUMNS)) + ["'pending'"])

_STAGING_MERGE = f"""
MERGE dbo.emu_staging AS t
USING (SELECT ? AS irn) AS s
  ON t.irn = s.irn
WHEN MATCHED THEN UPDATE SET
    {_UPDATE_SET},
    synced = 0,
    sync_failed = 0,
    status = 'pending',
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


# --- routing status ----------------------------------------------------------

STATUS_PENDING = "pending"   # staged, not routed yet - neither DSS task reads it
STATUS_READY = "ready"       # NetX has an asset with this IRN
STATUS_HOLDING = "holding"   # NetX has none yet; re-checked every run

_STATUS_CHUNK = 500  # well under SQL Server's 2100-parameter limit


def get_rows_to_route(conn):
    """[(irn, status)] for every row routing.py should look at: new/changed
    rows ('pending') plus parked rows ('holding') that need a re-check."""
    rows = conn.execute(
        "SELECT irn, status FROM dbo.emu_staging "
        "WHERE status IN ('pending', 'holding') AND irn IS NOT NULL"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def set_status(conn, irns, status):
    """Set `status` on the given IRNs (only rows still pending/holding, so a
    concurrent change is never clobbered). Moving to 'ready' also resets
    synced / sync_failed so the ready DSS task picks the row up - a row
    promoted out of 'holding' may carry stale flags."""
    irns = list(irns)
    reset = ", synced = 0, sync_failed = 0" if status == STATUS_READY else ""
    for i in range(0, len(irns), _STATUS_CHUNK):
        chunk = irns[i:i + _STATUS_CHUNK]
        marks = ", ".join(["?"] * len(chunk))
        conn.execute(
            f"UPDATE dbo.emu_staging SET status = ?{reset} "
            f"WHERE irn IN ({marks}) AND status IN ('pending', 'holding')",
            [status, *chunk],
        )
        conn.commit()
