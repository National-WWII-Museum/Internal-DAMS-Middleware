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
LOG_DIR = Path(os.getenv("LOG_DIR") or Path(__file__).resolve().parent.parent / "logs")

# Read-only login for the NetX database itself (video clip times live there).
# Unset = the clips endpoints answer 503 instead of the app failing to start.
NETX_DB_NAME = os.getenv("NETX_DB_NAME")
NETX_DB_USER = os.getenv("NETX_DB_USER")
NETX_DB_PASSWORD = os.getenv("NETX_DB_PASSWORD")

NETX_DB_CONNECTION_STRING = (
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={_server};"
    f"DATABASE={NETX_DB_NAME};"
    f"UID={NETX_DB_USER};"
    f"PWD={NETX_DB_PASSWORD};"
    f"Encrypt={DB_ENCRYPT};"
    f"TrustServerCertificate={DB_TRUST_SERVER_CERT};"
) if (NETX_DB_NAME and NETX_DB_USER and NETX_DB_PASSWORD) else None
