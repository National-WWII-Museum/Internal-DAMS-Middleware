from fastapi import APIRouter, Request

from common import logfiles

from ..templating import templates

router = APIRouter()

LEVEL_LABELS = {
    "all": "All entries",
    "warnings": "Warnings and errors",
    "errors": "Errors only",
}
LINE_CHOICES = (100, 200, 500, 1000)


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _size_label(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    return f"{max(n // 1000, 1) if n else 0} KB"


@router.get("/logs")
def logs_page(
    request: Request,
    log: str = "pipeline",
    level: str = "all",
    lines: str = "200",
    version: str = "0",
):
    # The form can send blanks or odd values; normalise instead of erroring.
    log = log if log in logfiles.LOG_NAMES else "pipeline"
    level = level if level in logfiles.LEVEL_FILTERS else "all"
    lines = _to_int(lines, 200)
    lines = lines if lines in LINE_CHOICES else 200
    versions = logfiles.available_versions(log)
    version = _to_int(version, 0)
    version = version if version in versions else 0

    result = logfiles.read_log(log, version=version, level=level, limit=lines)

    return templates.TemplateResponse(
        request, "logs.html",
        {
            "f": {"log": log, "level": level, "lines": lines, "version": version},
            "log_names": logfiles.LOG_NAMES,
            "level_labels": LEVEL_LABELS,
            "line_choices": LINE_CHOICES,
            "versions": versions or [0],
            "file_name": logfiles.log_path(log, version).name,
            "size_label": _size_label(result["size"]),
            "r": result,
        },
    )
