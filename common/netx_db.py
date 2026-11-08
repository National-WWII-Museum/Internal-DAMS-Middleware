"""
netx_db.py
Read-only access to the NetX database, for data the NetX JSON-RPC API doesn't
expose (video clip start/end times). Uses its own login (netx_readonly,
SELECT on dbo.constituent and dbo.image only - see
scripts/sql/002_netx_readonly_login.sql), separate from the EmuStaging
connection in db.py.

Never writes. Never touches EmuStaging.
"""
import pyodbc

from .config import NETX_DB_CONNECTION_STRING

# constituent.type for video clips (seen on asset 206839). Keyframes use a
# different type.
CLIP_TYPE = 4


def get_netx_connection():
    if not NETX_DB_CONNECTION_STRING:
        raise pyodbc.Error("NETX_DB_NAME / NETX_DB_USER / NETX_DB_PASSWORD are not set in .env")
    return pyodbc.connect(NETX_DB_CONNECTION_STRING, timeout=5)


def get_netx_db():
    """FastAPI dependency: one NetX connection per request, always closed."""
    conn = get_netx_connection()
    try:
        yield conn
    finally:
        conn.close()


def ms_to_clock(ms):
    """90500 -> '00:01:30.500'"""
    ms = int(ms)
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


# The most assets one request may ask for. Keeps the IN (...) list far under
# SQL Server's 2100-parameter limit.
MAX_ASSETS = 100


def get_clips(conn, asset_ids):
    """Clips for each asset id: {asset_id: {"filename": str, "clips": [...]}}.

    An asset that doesn't exist in NetX is left out of the result; an asset
    that exists but has no clips maps to an empty list.
    """
    asset_ids = list(dict.fromkeys(asset_ids))  # de-dupe, keep order
    marks = ",".join("?" * len(asset_ids))

    result = {}
    for image_id, name in conn.execute(
        f"SELECT image_id, name FROM dbo.image WHERE image_id IN ({marks})", asset_ids
    ).fetchall():
        result[image_id] = {"filename": name, "clips": []}

    if not result:
        return result

    found = list(result)
    marks = ",".join("?" * len(found))
    rows = conn.execute(
        "SELECT constituent_id, image_id, title, start_time, end_time, mod_date "
        f"FROM dbo.constituent WHERE type = ? AND image_id IN ({marks}) "
        "ORDER BY image_id, start_time, constituent_id",
        [CLIP_TYPE, *found],
    ).fetchall()

    for r in rows:
        result[r.image_id]["clips"].append({
            "constituent_id": r.constituent_id,
            "title": r.title,
            "start_ms": r.start_time,
            "end_ms": r.end_time,
            "start": ms_to_clock(r.start_time),
            "end": ms_to_clock(r.end_time),
            "modified": r.mod_date,
        })
    return result
