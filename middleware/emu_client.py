"""
emu_client.py
Reusable functions for talking to the EMu REST API (emurestapi shim):
authentication, and searching with pagination.
"""
import json
import requests

from . import config

# Placeholder field list - narrow it or expand it later once the NetX field
# mapping is finalized. irn and AdmDateModified are included because the
# polling/state logic depends on them regardless of what else gets added.
PLACEHOLDER_FIELDS = [
    "data.irn",
    "data.AdmDateModified",
    "data.AdmTimeModified",
    "data.WebTitle",
    "data.ObjRecordType",
]


def get_token(timeout=10):
    resp = requests.post(
        f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/tokens",
        json={"username": config.EMU_USERNAME, "password": config.EMU_PASSWORD},
        headers={"Content-Type": "application/json", "Prefer": "representation=minimal"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.headers["Authorization"]


def get_auth_headers(timeout=10):
    return {"Authorization": get_token(timeout=timeout)}


def extract_irn(record):
    """
    EMu's 'irn' field is returned as a nested reference object, not a plain
    value, e.g.:
        {"id": "emu:/nwwiim/ecatalogue/53935", "@controls": {...}}
    This pulls out just the numeric IRN as a string: "53935"
    """
    irn_field = record.get("irn")
    if isinstance(irn_field, dict):
        # id looks like "emu:/nwwiim/ecatalogue/53935" - take the last segment
        return irn_field.get("id", "").rstrip("/").split("/")[-1]
    # fallback, in case a response ever returns it as a plain value already
    return irn_field


def search_modified_since(module, since_date, fields=None, page_size=500, timeout=30):
    """
    Search an EMu module (e.g. 'ecatalogue') for records with
    AdmDateModified >= since_date, paging through all results.

    Returns a list of plain dicts (one per record), with 'irn' already
    normalized to a plain string via extract_irn().
    """
    if fields is None:
        fields = PLACEHOLDER_FIELDS

    headers = get_auth_headers(timeout=timeout)
    select_str = ",".join(fields)

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

    while True:
        if next_search_value is None:
            params = {
                "filter": json.dumps(filter_query),
                "limit": page_size,
                "select": select_str,
            }
            resp = requests.get(
                f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/{module}",
                headers=headers,
                params=params,
                timeout=timeout,
            )
            if resp.status_code != 200:                          # <-- ADD HERE
                print("EMu error response body:", resp.text[:1000])
        else:
            params = {
                "limit": page_size,
                "select": select_str,
            }
            resp = requests.get(
                f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/{module}",
                headers={**headers, "Next-Search": next_search_value},
                params=params,
                timeout=timeout,
            )

            if resp.status_code != 200:
                print("EMu error response body:", resp.text[:1000])

        resp.raise_for_status()
        data = resp.json()
        matches = data.get("matches", [])

        for m in matches:
            record_data = m.get("data", {})
            record_data["irn"] = extract_irn(record_data)
            all_records.append(record_data)

        next_search_value = resp.headers.get("Next-Search")
        if not next_search_value:
            break

    return all_records