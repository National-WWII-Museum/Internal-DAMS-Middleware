"""
config.py
The one place settings are read from .env. Both middleware/ and api/
import from here, so a setting only ever has to change in one spot.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- EMu REST API ---
EMU_HOST = os.getenv("EMU_HOST")
EMU_PORT = os.getenv("EMU_PORT")
EMU_TENANT = os.getenv("EMU_TENANT")
EMU_USERNAME = os.getenv("EMU_USERNAME")
EMU_PASSWORD = os.getenv("EMU_PASSWORD")

EMU_BASE_URL = f"http://{EMU_HOST}:{EMU_PORT}"

# --- NetX JSON-RPC API ---
NETX_BASE_URL = (os.getenv("NETX_BASE_URL") or "").rstrip("/")
# .strip() guards against a trailing newline when the token is pasted into .env
NETX_API_TOKEN = (os.getenv("NETX_API_TOKEN") or "").strip() or None

# Shared secret NetX sends with the clips custom-action webhook.
NETX_WEBHOOK_TOKEN_CLIPS = os.getenv("NETX_WEBHOOK_TOKEN_CLIPS")

# --- SQL Server (shared by EmuStaging and the NetX database) ---
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_HOST = os.getenv("DB_HOST")
# Leave DB_PORT blank for a named instance (e.g. HOST\INSTANCE) - the SQL
# Browser service resolves its dynamic port. Only set it for a default
# instance reached by a fixed TCP port.
DB_PORT = os.getenv("DB_PORT", "")
DB_ENCRYPT = os.getenv("DB_ENCRYPT", "yes")
# Driver 18 defaults Encrypt=yes and will reject a self-signed server cert
# unless this is yes (the SSMS connection uses TrustServerCertificate=True).
DB_TRUST_SERVER_CERT = os.getenv("DB_TRUST_SERVER_CERT", "yes")

_server = f"{DB_HOST},{DB_PORT}" if DB_PORT else DB_HOST


def _connection_string(database, user, password):
    return (
        f"DRIVER={{{DB_DRIVER}}};"
        f"SERVER={_server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"Encrypt={DB_ENCRYPT};"
        f"TrustServerCertificate={DB_TRUST_SERVER_CERT};"
    )


# --- EmuStaging database (sync_state, emu_staging, netx_staging) ---
# Schema is owned/provisioned by the DBA - this app only reads/writes rows.
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

DB_CONNECTION_STRING = _connection_string(DB_NAME, DB_USER, DB_PASSWORD)

# --- NetX database (read-only login; video clip times live there) ---
# Unset = the clips endpoints answer 503 instead of the app failing to start.
NETX_DB_NAME = os.getenv("NETX_DB_NAME")
NETX_DB_USER = os.getenv("NETX_DB_USER")
NETX_DB_PASSWORD = os.getenv("NETX_DB_PASSWORD")

NETX_DB_CONNECTION_STRING = (
    _connection_string(NETX_DB_NAME, NETX_DB_USER, NETX_DB_PASSWORD)
    if (NETX_DB_NAME and NETX_DB_USER and NETX_DB_PASSWORD)
    else None
)

# --- Logs ---
# Folder holding the middleware's *.log files (read by the API's Logs page).
# Defaults to <repo root>/logs, where the middleware writes them.
LOG_DIR = Path(os.getenv("LOG_DIR") or Path(__file__).resolve().parent.parent / "logs")
