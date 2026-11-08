import json
import logging
from pathlib import Path

import pyodbc
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from common.logging_setup import setup_named_logger
from common.db import get_connection

from .routers import clips, logs, records, ui

logger = logging.getLogger(__name__)

# Webhook test payloads go to data\webhook.log (viewable on the Logs page),
# since the API runs as a service with no console to watch.
webhook_logger = setup_named_logger("api.webhook", "webhook")

# Manual deletes from the Records page go to data\staging.log
staging_logger = setup_named_logger("api.staging", "staging")

app = FastAPI(title="Records in Que")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(ui.router)
app.include_router(logs.router)
app.include_router(clips.router)
app.include_router(records.router)

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
    webhook_logger.info("Webhook test received:\n%s", json.dumps(payload, indent=2, default=str))
    return payload
