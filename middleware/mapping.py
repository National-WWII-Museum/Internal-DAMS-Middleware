"""
mapping.py
Turn a normalized EMu ecatalogue record (as returned by emu_client, with
references already resolved) into a dict of dbo.emu_staging column values.

Rules (see project notes / schema comments):

- EMu hands back empty strings and empty arrays freely. Every one becomes
  None so the downstream NetX push can skip nulls - an empty string that
  slipped through would blank out a NetX value.
- Multi-value fields land in the format NetX writes for that attribute type:
    * plain-text attributes  -> quoted CSV, '"a","b","c"' (every value quoted,
      even a lone one; embedded double quotes doubled)     -> _pack_csv()
    * option-set attributes   -> bare comma, no space, 'a,b,c' (NetX renders
      option_set_item names, never quotes them)            -> _pack_optionset()
- title comes from the TitTitleType_grp entry whose TitTitleType is "Main"
  (falling back to the first title, then a bare TitTitle field).
- latitude / longitude are the (single-valued) coordinate fields off the
  first resolved SubGeographyRef_tab entry.
- modified_at combines AdmDateModified + AdmTimeModified and is what the
  watermark should compare against; the raw date_modified / time_modified
  are kept alongside for fidelity.
"""
import json
from datetime import date, datetime
from itertools import zip_longest

# emu_staging columns the middleware writes. Everything else on the table is
# either DB-managed bookkeeping (irn, synced, sync_failed, synced_at,
# first_seen_at, updated_at) or reserved for fields with no EMu source yet
# (alternate_title, collection_title, person, honorees, powkia, getty_geo_id,
# asset_url, asset_type).
WRITE_COLUMNS = [
    "date_modified",
    "time_modified",
    "modified_at",
    "record_type",
    "title",
    "accession_number",
    "credit_line",
    "collection_description",
    "donor_name",
    "hometown",
    "video_length",
    "latitude",
    "longitude",
    "units",
    "geography",
    "topical_subjects",
    "object_types",
    "organizations",
    "theaters",
    "branches",
    "local_terms",
    "battle_events",
    "brief_summary",
    "interview_summary",
    "summary_data",
    "formats",
    "interview_date",
    "geo_hierarchy",
    "raw_json",
]


def _clean(value):
    """Empty string / whitespace / empty list -> None. Otherwise trimmed."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, tuple)):
        cleaned = [c for c in (_clean(v) for v in value) if c is not None]
        return cleaned or None
    return value


def _as_list(value):
    """Normalize a possibly-scalar / possibly-None EMu field to a list."""
    cleaned = _clean(value)
    if cleaned is None:
        return []
    return cleaned if isinstance(cleaned, list) else [cleaned]


def _scalar(value):
    """First usable value of a field that should be single-valued (EMu will
    sometimes return a 1-element list where a scalar is expected)."""
    items = _as_list(value)
    return items[0] if items else None


def _truncate(value, max_len):
    if value is None:
        return None
    return str(value)[:max_len]


def _pack_csv(value):
    """Pack a plain-text multi-value field as quoted CSV: '"a","b"'. Every
    value quoted (matches how NetX writes type-1 attributes). Empty -> None."""
    items = _as_list(value)
    if not items:
        return None
    return ",".join('"' + str(v).replace('"', '""') + '"' for v in items)


def _pack_csv_bare_single(value):
    """Like _pack_csv, but a lone value is written bare (no quotes) to match
    existing single-valued plain-text data; 2+ values use quoted CSV.
    Used for Geography, where every existing NetX row is a bare single value
    but the EMu source (WebGeography_tab) is repeatable."""
    items = _as_list(value)
    if not items:
        return None
    if len(items) == 1:
        return str(items[0])
    return _pack_csv(items)


def _pack_optionset(value):
    """Pack an option-set multi-value field as bare comma, no space: 'a,b,c'
    (matches how NetX renders option_set_item names). Empty -> None."""
    items = _as_list(value)
    if not items:
        return None
    return ",".join(str(v) for v in items)


def _group_values(record, group, field):
    """Pull `field` from every entry of an EMu `_grp` group, tolerating both
    the list-of-dicts shape and a flattened parallel-array fallback."""
    grp = record.get(group)
    if isinstance(grp, dict):
        grp = [grp]
    if isinstance(grp, list):
        out = [
            _clean(e.get(field)) if isinstance(e, dict) else _clean(e)
            for e in grp
        ]
        out = [v for v in out if v is not None]
        if out:
            return out
    return _as_list(record.get(field))


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def _extract_modified(record):
    """(date_modified, time_modified, modified_at) from AdmDateModified /
    AdmTimeModified. modified_at is a datetime2; the other two are the raw
    values kept for fidelity."""
    raw_date = _scalar(record.get("AdmDateModified"))
    raw_time = _scalar(record.get("AdmTimeModified"))
    d = _parse_date(raw_date)
    if d is None:
        return None, _truncate(raw_time, 20), None

    combined = datetime(d.year, d.month, d.day)
    if isinstance(raw_time, str):
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
            try:
                t = datetime.strptime(raw_time.strip(), fmt).time()
                combined = datetime.combine(d, t)
                break
            except ValueError:
                continue
    return d, _truncate(raw_time, 20), combined


def _extract_title(record):
    grp = record.get("TitTitleType_grp")
    entries = []
    if isinstance(grp, dict):
        grp = [grp]
    if isinstance(grp, list):
        for e in grp:
            if isinstance(e, dict):
                entries.append(
                    (_clean(e.get("TitTitleType")), _clean(e.get("TitTitle")))
                )
    if not entries:
        # flattened parallel-array shape
        types = _as_list(record.get("TitTitleType"))
        titles = _as_list(record.get("TitTitle"))
        entries = list(zip_longest(types, titles))

    main = next((t for (ty, t) in entries if ty == "Main" and t), None)
    if main:
        return main
    return next((t for (_ty, t) in entries if t), None)


def _extract_geography(record):
    """(latitude, longitude, geo_hierarchy) from SubGeographyRef_tab, which
    emu_client.resolve_references  resolves this. 
    Uses the first reference if EMu returns several;"""
    ref = record.get("SubGeographyRef_tab")
    if isinstance(ref, list):
        ref = ref[0] if ref else None
    if not isinstance(ref, dict):
        return None, None, None
    return (
        _truncate(_scalar(ref.get("TgnNumericLatitude")), 100),
        _truncate(_scalar(ref.get("TgnNumericLongitude")), 100),
        _pack_csv(ref.get("HieHierarchyNotation_tab")),
    )


def record_to_staging_row(record):
    """Map one resolved EMu record to a dict keyed by WRITE_COLUMNS."""
    date_modified, time_modified, modified_at = _extract_modified(record)
    latitude, longitude, geo_hierarchy = _extract_geography(record)

    row = {
        "date_modified": date_modified,
        "time_modified": time_modified,
        "modified_at": modified_at,
        "record_type": _truncate(_scalar(record.get("ObjRecordType")), 100),
        "title": _truncate(_extract_title(record), 1000),
        "accession_number": _truncate(_scalar(record.get("AcqAccessionNumber")), 200),
        "credit_line": _truncate(_scalar(record.get("WebCreditLine")), 1000),
        "collection_description": _clean(_scalar(record.get("WebCollectionDescription"))),
        "donor_name": _truncate(_scalar(record.get("WebDonorName")), 510),
        "hometown": _truncate(_scalar(record.get("WebHometown")), 510),
        "video_length": _truncate(_scalar(record.get("VidOverallPlayingTime")), 100),
        "latitude": latitude,
        "longitude": longitude,
        "units": _pack_csv(record.get("WebUnit_tab")),
        "geography": _pack_csv_bare_single(record.get("WebGeography_tab")),
        "topical_subjects": _pack_csv(record.get("SubTopicalSubject_tab")),
        "object_types": _pack_csv(record.get("WebObjectType_tab")),
        "organizations": _pack_csv(record.get("WebOrganization_tab")),
        # option-set attributes
        "theaters": _pack_optionset(record.get("WebTheatre_tab")),
        "branches": _pack_optionset(record.get("WebBranch_tab")),
        "local_terms": _pack_optionset(record.get("WebLocalTerms_tab")),
        "battle_events": _pack_optionset(record.get("WebBattleEvent_tab")),
        "brief_summary": _clean(_scalar(record.get("ObjBriefSummary"))),
        "interview_summary": _clean(_scalar(record.get("ExtInterviewSummary"))),
        "summary_data": _clean(_scalar(record.get("SummaryData"))),
        "formats": _pack_csv(_group_values(record, "ExtFormat_grp", "ExtFormat")),
        "interview_date": _truncate(_scalar(record.get("IntInterviewDate0")), 50),
        "geo_hierarchy": geo_hierarchy,
        "raw_json": json.dumps(record, default=str, ensure_ascii=False),
    }

    missing = set(WRITE_COLUMNS) - set(row)
    extra = set(row) - set(WRITE_COLUMNS)
    if missing or extra:  # guard against WRITE_COLUMNS drifting out of sync
        raise RuntimeError(f"staging row/column mismatch: missing={missing} extra={extra}")
    return row
