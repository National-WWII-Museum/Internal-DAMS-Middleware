import logging
from pathlib import Path
from typing import Literal, Optional

import pyodbc
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from common import staging
from common.db import get_connection, get_db

from .routers import logs, ui

logger = logging.getLogger(__name__)

app = FastAPI(title="Records in Que")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(ui.router)
app.include_router(logs.router)

@app.exception_handler(pyodbc.Error)
async def database_error_handler(request, exc):
    # Any DB failure in any route ends up here: full detail in the log,
    # a generic message for the browser.
    logger.error("Database error on %s", request.url.path, exc_info=exc)
    return JSONResponse(status_code=503, content={"detail": "database unavailable"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    try:
        conn = get_connection()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
    except pyodbc.Error:
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="database unreachable")
    return {"status": "ok", "database": "reachable"}


# Temporary: echoes back whatever a webhook sends so we can inspect the payload.
@app.api_route("/webhook/test", methods=["GET", "POST", "PUT", "PATCH"])
async def webhook_test(request: Request):
    raw = await request.body()
    try:
        body = await request.json()
    except ValueError:
        body = raw.decode("utf-8", errors="replace")
    payload = {
        "method": request.method,
        "headers": dict(request.headers),
        "query": dict(request.query_params),
        "body": body,
    }
    logger.info("Webhook test received: %s", payload)
    return payload


@app.get("/api/status-counts")
def status_counts(conn=Depends(get_db)):
    return staging.get_status_counts(conn)

@app.get("/api/records")
def records(
    status: Optional[Literal["pending", "ready", "holding", "missing_file"]] = None,
    q: Optional[str] = Query(None, max_length=100),
    failed: bool = False,
    sort: Literal["updated", "newest", "oldest"] = "updated",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    conn=Depends(get_db),
):
    return staging.get_records(
        conn,
        status=status,
        q=(q or "").strip() or None,
        failed=failed,
        sort=sort,
        page=page,
        page_size=page_size,
    )