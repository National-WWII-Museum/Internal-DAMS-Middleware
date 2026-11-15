import json
import logging
from pathlib import Path

import pyodbc
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from common.logging_setup import setup_named_logger
from common.db import get_connection

from .routers import clips, logs, ui

logger = logging.getLogger(__name__)

# Webhook test payloads go to logs\webhook.log 
webhook_logger = setup_named_logger("api.webhook", "webhook")

# Manual deletes from the Records page go to logs\staging.log
staging_logger = setup_named_logger("api.staging", "staging")

app = FastAPI(title="Records in Que")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(ui.router)
app.include_router(logs.router)
app.include_router(clips.router)

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

