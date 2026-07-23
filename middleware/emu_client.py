import json

import requests

from . import config

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


def search_modified_since(module, since_date, fields=None, page_size=500, timeout=30):
    """
    Search an EMu module (e.g. 'ecatalogue') for records with
    AdmDateModified >= since_date, paging through all results.

    Returns a list of records (each record's 'data' dict).
    """
    if fields is None:
        fields = PLACEHOLDER_FIELDS

    headers = get_auth_headers(timeout=timeout)
    select_str = ";".join(fields)

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

    base_params = {
        "filter": filter_query,
        "limit": page_size,
        "select": select_str,
    }

    all_records = []
    next_search_value = None

    while True:
        if next_search_value is None:
            params = {
                "filter": json.dumps(base_params["filter"]),
                "limit": base_params["limit"],
                "select": base_params["select"],
            }
            resp = requests.get(
                f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/{module}",
                headers=headers,
                params=params,
                timeout=timeout,
            )
        else:
            params = {
                "limit": base_params["limit"],
                "select": base_params["select"],
            }
            resp = requests.get(
                f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/{module}",
                headers={**headers, "Next-Search": next_search_value},
                params=params,
                timeout=timeout,
            )

        resp.raise_for_status()
        data = resp.json()
        matches = data.get("matches", [])
        all_records.extend(m.get("data", {}) for m in matches)

        next_search_value = resp.headers.get("Next-Search")
        if not next_search_value:
            break

    return all_records