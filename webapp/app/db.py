import pyodbc

from .config import DB_CONNECTION_STRING


def get_connection():
    # timeout = login timeout in seconds, so a dead DB fails fast
    return pyodbc.connect(DB_CONNECTION_STRING, timeout=5)

def get_db():
    """open a connection for one request, always close it."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()