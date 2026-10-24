"""
logfiles.py
Read the middleware's log files for the API's Logs page.

Only the names in LOG_NAMES can be read, and the file path is always built
here from LOG_DIR - nothing a browser sends ever becomes part of a path.
The file is opened, read and closed straight away (never held open), so the
middleware's log rotation - which renames the file - is not blocked on Windows.
"""
import re
from datetime import datetime

from .config import LOG_DIR

LOG_NAMES = ("pipeline", "polling", "sweep", "routing", "requeue")

# How many rotated copies the middleware keeps (backupCount in its handler).
MAX_BACKUPS = 5

# Never read more than this from the end of a file, so an old log that grew
# huge before rotation was added can't make a page request slow.
MAX_READ_BYTES = 8_000_000

LEVEL_FILTERS = {
    "all": None,
    "warnings": {"WARNING", "ERROR", "CRITICAL"},
    "errors": {"ERROR", "CRITICAL"},
}

# "2026-10-24 07:00:01,123 INFO middleware.polling: message"
_ENTRY_START = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} (\w+) ")


def log_path(name, version=0):
    """Path of a log file. version 0 = current, 1..MAX_BACKUPS = rotated copies."""
    if name not in LOG_NAMES:
        raise ValueError(f"unknown log: {name!r}")
    if not 0 <= version <= MAX_BACKUPS:
        raise ValueError(f"bad version: {version!r}")
    suffix = ".log" if version == 0 else f".log.{version}"
    return LOG_DIR / f"{name}{suffix}"


def available_versions(name):
    """Versions of this log that exist on disk, e.g. [0, 1, 2]."""
    return [v for v in range(MAX_BACKUPS + 1) if log_path(name, v).exists()]


def _css_class(level):
    if level in ("ERROR", "CRITICAL"):
        return "error"
    if level == "WARNING":
        return "warning"
    return "info"


def read_log(name, *, version=0, level="all", limit=200):
    """
    Entries from one log file, newest first.

    An entry is a log line plus any lines that follow it without their own
    timestamp (a traceback stays attached to the error that caused it).
    """
    path = log_path(name, version)
    result = {
        "exists": False, "size": 0, "modified": None, "truncated": False,
        "errors": 0, "warnings": 0, "matching": 0, "records": [],
    }

    try:
        stat = path.stat()
        with open(path, "rb") as f:
            start = max(0, stat.st_size - MAX_READ_BYTES)
            f.seek(start)
            raw = f.read()
    except FileNotFoundError:
        return result

    if start > 0:
        # we landed mid-line: drop the partial first line
        raw = raw.split(b"\n", 1)[1] if b"\n" in raw else b""
        result["truncated"] = True

    result["exists"] = True
    result["size"] = stat.st_size
    result["modified"] = datetime.fromtimestamp(stat.st_mtime)

    text = raw.decode("utf-8", errors="replace")  # older lines may be cp1252

    records = []
    for line in text.splitlines():
        m = _ENTRY_START.match(line)
        if m or not records:
            lvl = m.group(2) if m else ""
            records.append({"level": lvl, "css": _css_class(lvl), "text": line})
        else:
            records[-1]["text"] += "\n" + line

    result["errors"] = sum(1 for r in records if r["level"] in ("ERROR", "CRITICAL"))
    result["warnings"] = sum(1 for r in records if r["level"] == "WARNING")

    wanted = LEVEL_FILTERS.get(level)
    if wanted:
        records = [r for r in records if r["level"] in wanted]
    result["matching"] = len(records)

    result["records"] = list(reversed(records[-limit:]))
    return result
