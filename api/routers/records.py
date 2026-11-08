"""
records.py
JSON endpoints for the EmuStaging queue: status counts and the paged,
filterable record list (the data behind the dashboard and Records page).

  GET /api/status-counts
  GET /api/records
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query

from common import staging
from common.db import get_db

router = APIRouter()


@router.get("/api/status-counts")
def status_counts(conn=Depends(get_db)):
    return staging.get_status_counts(conn)


@router.get("/api/records")
def records(
    status: Optional[Literal["pending", "ready", "holding"]] = None,
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
