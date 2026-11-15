"""
netx_staging.py
Reads and writes for dbo.netx_staging: one row per NetX webhook event
(see refrence/scripts/sql/004_netx_staging.sql). The mirror of staging.py,
which does the same job for dbo.emu_staging.
"""

import json

import pyodbc

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