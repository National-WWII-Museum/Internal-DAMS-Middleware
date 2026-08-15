"""
emu_client.py
Reusable functions for talking to the EMu REST API:
authentication, and searching with pagination.
"""
import json
import logging
from datetime import datetime, timedelta

import requests

from . import config

logger = logging.getLogger(__name__)

# Placeholder field list - narrow it or expand it later once the NetX field
# mapping is finalized. irn and AdmDateModified are included because the
# polling/state logic depends on them regardless of what else gets added.
PLACEHOLDER_FIELDS = [
    "data.AdmDateModified",
    "data.AdmTimeModified",
    "data.irn",
    "data.ObjRecordType",
    "data.TitTitleType_grp.TitTitle"
    "data.AcqAccessionNumber"
    "data.ColOrganization_tab",
    "data.ColTheatre_tab",
    "data.ColBranchOfService_tab",
    "data.ColUnit_tab",
    "data.SubLocalTerms_tab",
    "data.SubGeographyRef_tab"
    "data.ObjBriefSummary",
    "data.WebCollectionDescription",
    "data.WebCreditLine",
    "data.SubTopicalSubject_tab"
]

# Reference fields to follow into another module, and which fields to pull
# back from the target record. Add more entries here as more of the final
# JSON's fields turn out to live in a linked module rather than ecatalogue.
REFERENCE_FIELD_MAP = {
    "SubGeographyRef_tab": {
        "module": "ethesaurus",
        "fields": ["TgnNumericLatitude", "TgnNumericLongitude", "HieHierarchyNotation_tab"],
    },
}


class EMuAPIError(Exception):
    """Raised when the EMu REST API can't be reached or returns a non-2xx response.

    Wraps the underlying requests exception so callers (polling.py) get one
    exception type to catch and log, regardless of whether the failure was a
    network error, a timeout, or an HTTP error status.
    """


def get_token(timeout=10):
    try:
        resp = requests.post(
            f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/tokens",
            json={"username": config.EMU_USERNAME, "password": config.EMU_PASSWORD},
            headers={"Content-Type": "application/json", "Prefer": "representation=minimal"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise EMuAPIError(f"Failed to obtain auth token from EMu: {e}") from e
    return resp.headers["Authorization"]


def get_auth_headers(timeout=10):
    return {"Authorization": get_token(timeout=timeout)}


def extract_irn(record):
    """
    Extract 'irn' field for a nested reference object:
        {"id": "emu:/nwwiim/ecatalogue/53935", "@controls": {...}}
    This pulls out just the numeric IRN as a string: "53935"
    This is for requesting extra data for a record from different modules
    """
    irn_field = record.get("irn")
    if isinstance(irn_field, dict):
        # id looks like "emu:/nwwiim/ecatalogue/53935" - take the last segment
        return irn_field.get("id", "").rstrip("/").split("/")[-1]
    # fallback, in case a response ever returns it as a plain value already
    return irn_field


def _parse_ref_id(ref_id):
    """'emu:/nwwiim/ethesaurus/2873616' -> ('ethesaurus', '2873616')"""
    parts = ref_id.rstrip("/").split("/")
    return parts[-2], parts[-1]


def get_record(module, irn, fields=None, headers=None, timeout=30):
    """
    Fetch a single record by module + irn (GET /{tenant}/{module}/{irn}).
    Used to resolve a reference field to specific data in another module.

    Pass `headers` (from get_auth_headers()) when making many calls in a
    row - each call to get_auth_headers() logs in for a fresh token, and
    EMu will reject rapid-fire logins.
    """
    if headers is None:
        headers = get_auth_headers(timeout=timeout)
    params = {}
    if fields:
        # select needs the 'data.' prefix, same as the search endpoint -
        # a bare field name like 'TgnNumericLatitude' 400s.
        select_fields = [f if f.startswith("data.") else f"data.{f}" for f in fields]
        params["select"] = ",".join(select_fields)

    try:
        resp = requests.get(
            f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/{module}/{irn}",
            headers=headers,
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        raise EMuAPIError(f"EMu record fetch failed for {module}/{irn}: {e}") from e
    except ValueError as e:
        raise EMuAPIError(
            f"EMu returned an unparseable response for {module}/{irn}: {e}"
        ) from e

    return data.get("data", {})


def resolve_references(record, headers=None, timeout=30):
    """
    For every field in REFERENCE_FIELD_MAP present on this record, follow the
    reference(s) (a single {id, @controls} dict, or a list of them for a
    '_tab' field) and replace the stub with just the mapped fields pulled
    from the target module's record.

    Pass `headers` when resolving references for many records in a row (e.g.
    in a polling loop) so every lookup reuses one token instead of each one
    logging in fresh - see get_record().

    Mutates and returns `record`.
    """
    if headers is None:
        headers = get_auth_headers(timeout=timeout)

    for field_name, mapping in REFERENCE_FIELD_MAP.items():
        value = record.get(field_name)
        if value is None:
            continue

        target_fields = mapping["fields"]

        def _resolve_one(ref):
            if not isinstance(ref, dict) or "id" not in ref:
                return ref
            module, irn = _parse_ref_id(ref["id"])
            return get_record(module, irn, fields=target_fields, headers=headers, timeout=timeout)

        if isinstance(value, list):
            record[field_name] = [_resolve_one(item) for item in value]
        else:
            record[field_name] = _resolve_one(value)

    return record


def search_modified_on(module, date, fields=None, page_size=500, timeout=30):
    """
    Search an EMu module (e.g. 'ecatalogue') for records with
    AdmDateModified falling on a single day, paging through all results.

    `date` is a "YYYY-MM-DD" string; the day after it is computed and used
    as the exclusive upper bound of the range.

    Returns a list of plain dicts (one per record), with 'irn' already
    normalized to a plain string via extract_irn().

    `fields` defaults to PLACEHOLDER_FIELDS. Pass an empty list to omit the
    'select' param entirely and get every field EMu has for each record.
    """
    if fields is None:
        fields = PLACEHOLDER_FIELDS

    next_day = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    headers = get_auth_headers(timeout=timeout)
    select_str = ",".join(fields) if fields else None

    filter_query = {
        "AND": [
            {
                "data.AdmDateModified": {
                    "range": {
                        "gte": date,
                        "lt": next_day,
                        "mode": "date",
                    }
                }
            }
        ]
    }

    all_records = []
    next_search_value = None
    page_num = 1

    while True:
        if next_search_value is None:
            params = {
                "filter": json.dumps(filter_query),
                "limit": page_size,
            }
            if select_str:
                params["select"] = select_str
            request_headers = headers
        else:
            params = {
                "limit": page_size,
            }
            if select_str:
                params["select"] = select_str
            request_headers = {**headers, "Next-Search": next_search_value}

        try:
            resp = requests.get(
                f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/{module}",
                headers=request_headers,
                params=params,
                timeout=timeout,
            )
            if resp.status_code != 200:
                logger.error(
                    "EMu returned %s on page %d for module %s: %s",
                    resp.status_code, page_num, module, resp.text[:1000],
                )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            raise EMuAPIError(
                f"EMu search failed for module '{module}' on page {page_num}: {e}"
            ) from e
        except ValueError as e:
            # resp.json() raises ValueError (json.JSONDecodeError) on bad payloads
            raise EMuAPIError(
                f"EMu returned an unparseable response for module '{module}' "
                f"on page {page_num}: {e}"
            ) from e

        matches = data.get("matches", [])

        for m in matches:
            record_data = m.get("data", {})
            record_data["irn"] = extract_irn(record_data)
            all_records.append(record_data)

        logger.debug("Fetched page %d for %s: %d record(s)", page_num, module, len(matches))

        next_search_value = resp.headers.get("Next-Search")
        if not next_search_value:
            break
        page_num += 1

    return all_records


def search_modified_since(module, since_date, fields=None, page_size=500, timeout=30):
    """
    Search an EMu module (e.g. 'ecatalogue') for records with
    AdmDateModified >= since_date, paging through all results.

    Returns a list of plain dicts (one per record), with 'irn' already
    normalized to a plain string via extract_irn().

    `fields` defaults to PLACEHOLDER_FIELDS. Pass an empty list to omit the
    'select' param entirely and get every field EMu has for each record.
    """
    if fields is None:
        fields = PLACEHOLDER_FIELDS

    headers = get_auth_headers(timeout=timeout)
    select_str = ",".join(fields) if fields else None

    filter_query = {
        "AND": [
            {
                "data.AdmDateModified": {
                    "range": {
                        "gte": since_date,
                        "mode": "date",
                    }
                }
            }
        ]
    }

    all_records = []
    next_search_value = None
    page_num = 1

    while True:
        if next_search_value is None:
            params = {
                "filter": json.dumps(filter_query),
                "limit": page_size,
            }
            if select_str:
                params["select"] = select_str
            request_headers = headers
        else:
            params = {
                "limit": page_size,
            }
            if select_str:
                params["select"] = select_str
            request_headers = {**headers, "Next-Search": next_search_value}

        try:
            resp = requests.get(
                f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/{module}",
                headers=request_headers,
                params=params,
                timeout=timeout,
            )
            if resp.status_code != 200:
                logger.error(
                    "EMu returned %s on page %d for module %s: %s",
                    resp.status_code, page_num, module, resp.text[:1000],
                )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            raise EMuAPIError(
                f"EMu search failed for module '{module}' on page {page_num}: {e}"
            ) from e
        except ValueError as e:
            # resp.json() raises ValueError (json.JSONDecodeError) on bad payloads
            raise EMuAPIError(
                f"EMu returned an unparseable response for module '{module}' "
                f"on page {page_num}: {e}"
            ) from e

        matches = data.get("matches", [])

        for m in matches:
            record_data = m.get("data", {})
            record_data["irn"] = extract_irn(record_data)
            all_records.append(record_data)

        logger.debug("Fetched page %d for %s: %d record(s)", page_num, module, len(matches))

        next_search_value = resp.headers.get("Next-Search")
        if not next_search_value:
            break
        page_num += 1

    return all_records