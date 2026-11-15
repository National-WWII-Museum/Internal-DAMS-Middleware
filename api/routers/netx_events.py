"""
netx_events.py
The "NetX events" page: a read-only list of dbo.netx_staging, one row per
webhook delivery from NetX (see api/routers/clips.py for where rows are made).
"""
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request

from common import netx_staging
from common.db import get_db

from ..templating import templates

router = APIRouter()

PAGE_SIZE = 50


def _events_url(status, page):
    params = {}
    if status:
        params["status"] = status
    if page > 1:
        params["page"] = page
    return "/netx-events?" + urlencode(params) if params else "/netx-events"


@router.get("/netx-events")
def netx_events_page(
    request: Request,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    conn=Depends(get_db),
):
    # The form can send blanks or odd values; normalise instead of erroring.
    status = status if status in netx_staging.STATUSES else None

    result = netx_staging.get_events(conn, status=status, page=page, page_size=PAGE_SIZE)
    total, items = result["total"], result["items"]
    total_pages = max(result["total_pages"], 1)
    start = (page - 1) * PAGE_SIZE + 1 if items else 0

    return templates.TemplateResponse(
        request, "netx_events.html",
        {
            "f": {"status": status},
            "statuses": netx_staging.STATUSES,
            "items": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "start": start,
            "end": start + len(items) - 1 if items else 0,
            "prev_url": _events_url(status, page - 1) if page > 1 else None,
            "next_url": _events_url(status, page + 1) if page < total_pages else None,
        },
    )
