"""
test_clips.py
One-off check that we can read video clip start/end times for a NetX asset.
The public NetX API has no clip method, so this reads the NetX database's
`constituent` table directly. Read-only: it only runs SELECTs.

In `constituent`, clips are type 4 (seen on asset 206839: constituent_id,
image_id, type, title, start_time, end_time in milliseconds, mod_date).
Keyframes use a different type; use --type to look at other rows.

Connection: same server as the rest of the app (DB_* in .env), but pointed at
the NetX database with its own read-only login. Set in .env:
    NETX_DB_NAME=NetX
    NETX_DB_USER=netx_readonly
    NETX_DB_PASSWORD=...
(create the login with scripts/sql/002_netx_readonly_login.sql). If the user
and password are unset it falls back to DB_USER/DB_PASSWORD, which will not
have access to the NetX database.

Run from the repo root:
    python -m scripts.test_clips 206839 --database <NetX DB name>
    python -m scripts.test_clips 206839 206840
    python -m scripts.test_clips 206839 --type 0     # see what other types hold
"""
import argparse
import os
import sys

import pyodbc

from middleware import config

CLIP_TYPE = 4


def ms_to_clock(ms):
    """90500 -> '00:01:30.500'"""
    ms = int(ms)
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def connect(database):
    # Reuse the app's server/login/driver settings, swapping only the database.
    # Prefer the dedicated read-only login (NETX_DB_USER / NETX_DB_PASSWORD).
    user = os.getenv("NETX_DB_USER") or config.DB_USER
    password = os.getenv("NETX_DB_PASSWORD") or config.DB_PASSWORD
    server = f"{config.DB_HOST},{config.DB_PORT}" if config.DB_PORT else config.DB_HOST
    conn_str = (
        f"DRIVER={{{config.DB_DRIVER}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"Encrypt={config.DB_ENCRYPT};"
        f"TrustServerCertificate={config.DB_TRUST_SERVER_CERT};"
    )
    return pyodbc.connect(conn_str, timeout=15)


QUERY = """
SELECT c.constituent_id, c.image_id, c.type, c.title,
       c.start_time, c.end_time, c.mod_date
FROM dbo.constituent AS c
WHERE c.image_id = ? AND c.type = ?
ORDER BY c.start_time, c.constituent_id
"""

NAME_QUERY = "SELECT name FROM dbo.image WHERE image_id = ?"


def main():
    parser = argparse.ArgumentParser(description="Print video clip timestamps for NetX assets.")
    parser.add_argument("asset_ids", nargs="+", type=int, help="NetX asset (image) IDs")
    parser.add_argument("--database", default=os.getenv("NETX_DB_NAME"),
                        help="NetX database name (default: NETX_DB_NAME from .env)")
    parser.add_argument("--type", type=int, default=CLIP_TYPE,
                        help=f"constituent.type to read (default {CLIP_TYPE} = clips)")
    args = parser.parse_args()

    if not args.database:
        sys.exit("No NetX database name. Set NETX_DB_NAME in .env or pass --database.")

    conn = connect(args.database)
    try:
        for asset_id in args.asset_ids:
            row = conn.execute(NAME_QUERY, asset_id).fetchone()
            filename = row[0] if row else "(not found in image table)"
            rows = conn.execute(QUERY, asset_id, args.type).fetchall()

            print(f"\nasset {asset_id}: {filename}")
            print(f"  {len(rows)} row(s) with type={args.type}")
            if not rows:
                continue

            print(f"  {'id':>8}  {'title':<20} {'start':>12} {'end':>12}  "
                  f"{'start (ms)':>10} {'end (ms)':>10}  modified")
            for r in rows:
                start, end = r.start_time, r.end_time
                print(f"  {r.constituent_id:>8}  {str(r.title or ''):<20.20} "
                      f"{ms_to_clock(start):>12} {ms_to_clock(end):>12}  "
                      f"{start:>10} {end:>10}  {r.mod_date:%Y-%m-%d %H:%M}")

            bad = [r.constituent_id for r in rows if r.end_time <= r.start_time]
            if bad:
                print(f"  WARNING: end_time <= start_time for constituent(s) {bad}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
