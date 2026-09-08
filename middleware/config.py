import os
from dotenv import load_dotenv

load_dotenv()

EMU_HOST = os.getenv("EMU_HOST")
EMU_PORT = os.getenv("EMU_PORT")
EMU_TENANT = os.getenv("EMU_TENANT")
EMU_USERNAME = os.getenv("EMU_USERNAME")
EMU_PASSWORD = os.getenv("EMU_PASSWORD")

EMU_BASE_URL = f"http://{EMU_HOST}:{EMU_PORT}"

# --- Sync-state database (remote MS SQL Server, via pyodbc) ---
# Schema is owned/provisioned by the DBA - this app only reads/writes rows.
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_HOST = os.getenv("DB_HOST")
# Leave DB_PORT blank for a named instance (e.g. HOST\INSTANCE) - the SQL
# Browser service resolves its dynamic port. Only set it for a default
# instance reached by a fixed TCP port.
DB_PORT = os.getenv("DB_PORT", "")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_ENCRYPT = os.getenv("DB_ENCRYPT", "yes")
# Driver 18 defaults Encrypt=yes and will reject a self-signed server cert
# unless this is yes (the SSMS connection uses TrustServerCertificate=True).
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
