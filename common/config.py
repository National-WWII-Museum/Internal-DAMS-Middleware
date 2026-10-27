import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_HOST = os.getenv("DB_HOST")
# Blank for a named instance (HOST\INSTANCE); set for a fixed TCP port.
DB_PORT = os.getenv("DB_PORT", "")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_ENCRYPT = os.getenv("DB_ENCRYPT", "yes")
DB_TRUST_SERVER_CERT = os.getenv("DB_TRUST_SERVER_CERT", "yes")

_server = f"{DB_HOST},{DB_PORT}" if DB_PORT else DB_HOST

DB_CONNECTION_STRING = (
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={_server};"
    f"DATABASE={DB_NAME};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
    f"Encrypt={DB_ENCRYPT};"
    f"TrustServerCertificate={DB_TRUST_SERVER_CERT};"
)

# Folder holding the middleware's *.log files (read by the API's Logs page).
# Defaults to <repo root>/data, where the middleware writes them.
LOG_DIR = Path(os.getenv("LOG_DIR") or Path(__file__).resolve().parent.parent / "data")
# Must match the token NetX sends in each webhook body (set per subscription
# in NetX). The webhook endpoint rejects everything while this is unset.
NETX_WEBHOOK_TOKEN = (os.getenv("NETX_WEBHOOK_TOKEN") or "").strip() or None
# Comma-separated NetX systemEventType values the webhook acts on, e.g.
# "ASSET_CREATE". Blank = act on every event type (each is still logged).
NETX_WEBHOOK_EVENTS = {e.strip() for e in (os.getenv("NETX_WEBHOOK_EVENTS") or "").split(",") if e.strip()}
