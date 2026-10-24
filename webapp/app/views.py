import csv
import io
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from pathlib import Path

from . import queries
from .db import get_db

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

PAGE_SIZE = 50
SORT_LABELS = {
    "updated": "Recently updated",
    "newest": "Newest first seen",
    "oldest": "Oldest first seen",
}


def _format_dt(value):
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


templates.env.filters["dt"] = _format_dt


def _records_url(status, q, failed, sort, page):
    params = {}
    if status:
        params["status"] = status
    if q:
        params["q"] = q
    if failed:
        params["failed"] = "true"
    if sort != "updated":
        params["sort"] = sort
    if page > 1:
        params["page"] = page
    return "/?" + urlencode(params) if params else "/"


@router.get("/")
def records_page(
    request: Request,
    status: Optional[str] = None,
    q: Optional[str] = None,
    failed: bool = False,
    sort: str = "updated",
    page: int = Query(1, ge=1),
    conn=Depends(get_db),
):
    # The form can send blanks or odd values; normalise instead of erroring.
    status = status if status in queries.STATUSES else None
    sort = sort if sort in queries.SORTS else "updated"
    q = (q or "").strip()[:100] or None

    result = queries.get_records(
        conn, status=status, q=q, failed=failed, sort=sort,
        page=page, page_size=PAGE_SIZE,
    )
    total, items = result["total"], result["items"]
    total_pages = max(result["total_pages"], 1)
    start = (page - 1) * PAGE_SIZE + 1 if items else 0

    return templates.TemplateResponse(
        request, "records.html",
        {
            "f": {"status": status, "q": q, "failed": failed, "sort": sort},
            "statuses": queries.STATUSES,
            "sorts": SORT_LABELS,
            "items": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "start": start,
            "end": start + len(items) - 1 if items else 0,
            "prev_url": _records_url(status, q, failed, sort, page - 1) if page > 1 else None,
            "next_url": _records_url(status, q, failed, sort, page + 1) if page < total_pages else None,
        },
    )


def _csv_cell(value):
    """Text for one CSV cell. A leading = + - @ would be run as a formula by
    Excel, so those get a leading apostrophe."""
    if value is None:
        return ""
    text = value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/holding.csv")
def holding_csv(conn=Depends(get_db)):
    columns, rows = queries.get_holding_export(conn)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_cell(v) for v in row])
    # The BOM makes Excel read the file as UTF-8 (names with accents).
    body = "\ufeff" + buffer.getvalue()
    filename = f"holding-{date.today().isoformat()}.csv"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )