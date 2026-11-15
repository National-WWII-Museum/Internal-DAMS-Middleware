"""
netx_staging.py
Reads and writes for dbo.netx_staging: one row per NetX webhook event
(see refrence/scripts/sql/004_netx_staging.sql). The mirror of emu_staging.py,
which does the same job for dbo.emu_staging.
"""

import json

import pyodbc

STATUSES = ("received", "done", "failed")

LIST_COLUMNS = (
    "event_id, event_type, asset_ids, netx_user_id, status, error, "
    "received_at, processed_at"
)


def _parse_asset_ids(text):
    """The asset_ids column is JSON text ('[206839, 206840]'); give the page a
    real list. Anything unreadable becomes an empty list instead of an error."""
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def get_events(conn, *, status, page, page_size):
    """One page of netx_staging rows, newest first, plus the total row count
    for the filter. Same shape as emu_staging.get_records."""
    where, params = ("WHERE status = ?", [status]) if status else ("", [])

    total = conn.execute(
        f"SELECT COUNT(*) FROM dbo.netx_staging {where}", params
    ).fetchone()[0]

    cur = conn.execute(
        f"SELECT {LIST_COLUMNS} FROM dbo.netx_staging {where} "
        "ORDER BY received_at DESC, event_id ASC "
        "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
        [*params, (page - 1) * page_size, page_size],
    )
    columns = [c[0] for c in cur.description]
    items = [dict(zip(columns, row)) for row in cur.fetchall()]
    for item in items:
        item["asset_ids"] = _parse_asset_ids(item["asset_ids"])

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
        "items": items,
    }


def record_event(conn, event_id, asset_ids, netx_user_id):
    """Insert the event. Returns True if it is new, False if NetX has
    already sent this event_id (a retry)."""
    try:
        conn.execute(
            "INSERT INTO dbo.netx_staging (event_id, asset_ids, netx_user_id) "
            "VALUES (?, ?, ?)",
            [event_id, json.dumps(asset_ids), netx_user_id],
        )
        conn.commit()
        return True
    except pyodbc.IntegrityError:
        # The primary key rejected it: this event_id is already in the table.
        conn.rollback()
        return False

def mark_done(conn, event_id):
    """Processing finished without an error."""
    conn.execute(
        "UPDATE dbo.netx_staging "
        "SET status = 'done', error = NULL, processed_at = SYSUTCDATETIME() "
        "WHERE event_id = ?",
        [event_id],
    )
    conn.commit()


def mark_failed(conn, event_id, error):
    """Processing raised an error; keep the message so it can be reviewed."""
    conn.execute(
        "UPDATE dbo.netx_staging "
        "SET status = 'failed', error = ?, processed_at = SYSUTCDATETIME() "
        "WHERE event_id = ?",
        [str(error)[:4000], event_id],
    )
    conn.commit()    