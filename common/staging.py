STATUSES = ("pending", "ready", "holding", "missing_file")


def get_status_counts(conn):
    """Row counts per routing status, plus how many rows have sync_failed set."""
    rows = conn.execute(
        """
        SELECT status,
               COUNT(*) AS total,
               SUM(CASE WHEN sync_failed = 1 THEN 1 ELSE 0 END) AS failed
        FROM dbo.emu_staging
        GROUP BY status
        """
    ).fetchall()

    by_status = {s: 0 for s in STATUSES}  # a status with no rows still shows as 0
    failed = 0
    for r in rows:
        by_status[r.status] = r.total
        failed += r.failed

    return {"total": sum(by_status.values()), "failed": failed, "by_status": by_status}

LIST_COLUMNS = (
    "irn, status, synced, sync_failed, synced_at, first_seen_at, updated_at, "
    "record_type, title, accession_number, file_name"
)


SORTS = {
    "updated": "updated_at DESC",
    "newest": "first_seen_at DESC",
    "oldest": "first_seen_at ASC",
}

def _escape_like(text):
    """Make %, _ and [ in the user's search text match literally in LIKE."""
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("[", "\\[")
    )


def _build_where(status, q, failed):
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if failed:
        clauses.append("sync_failed = 1")
    if q:
        like = f"%{_escape_like(q)}%"
        clauses.append(
            "(irn LIKE ? ESCAPE '\\' OR accession_number LIKE ? ESCAPE '\\' "
            "OR file_name LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')"
        )
        params.extend([like] * 4)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def get_records(conn, *, status, q, failed, sort, page, page_size):
    """One page of emu_staging rows plus the total row count for the filters."""
    where, params = _build_where(status, q, failed)

    total = conn.execute(
        f"SELECT COUNT(*) FROM dbo.emu_staging {where}", params
    ).fetchone()[0]

    cur = conn.execute(
        f"SELECT {LIST_COLUMNS} FROM dbo.emu_staging {where} "
        f"ORDER BY {SORTS[sort]}, irn ASC "
        "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
        [*params, (page - 1) * page_size, page_size],
    )
    columns = [c[0] for c in cur.description]
    items = [dict(zip(columns, row)) for row in cur.fetchall()]

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
        "items": items,
    }

def get_holding_export(conn):
    """Every 'holding' row, oldest first, for the CSV download. Reads the
    dbo.v_emu_holding view so the definition of 'holding' lives in one place."""
    cur = conn.execute(
        "SELECT irn, title, accession_number, file_name, first_seen_at, updated_at "
        "FROM dbo.v_emu_holding ORDER BY first_seen_at ASC, irn ASC"
    )
    return [c[0] for c in cur.description], cur.fetchall()