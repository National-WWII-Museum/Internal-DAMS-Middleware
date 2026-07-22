"""
count_matches.py
Count total records matching a filter by paging through results with a
minimal 'select' (just irn) and a large limit, since this emurestapi
build does not return a 'hits' field. Does not store or process full
record data - just tallies how many matches come back per page.
"""
import os
from dotenv import load_dotenv
import requests
import json

load_dotenv()
EMU_HOST = os.getenv("EMU_HOST")
EMU_PORT = os.getenv("EMU_PORT")
EMU_TENANT = os.getenv("EMU_TENANT")
EMU_USERNAME = os.getenv("EMU_USERNAME")
EMU_PASSWORD = os.getenv("EMU_PASSWORD")
EMU_BASE_URL = f"http://{EMU_HOST}:{EMU_PORT}"  # IPv4 now, no brackets needed

# --- Step 1: get a fresh token ---
token_resp = requests.post(
    f"{EMU_BASE_URL}/{EMU_TENANT}/tokens",
    json={"username": EMU_USERNAME, "password": EMU_PASSWORD},
    headers={"Content-Type": "application/json", "Prefer": "representation=minimal"},
    timeout=10,
)
token_resp.raise_for_status()
bearer = token_resp.headers["Authorization"]

# --- Step 2: define the filter (adjust date as needed) ---
filter_query = {
    "AND": [
        {
            "data.AdmDateModified": {
                "range": {
                    "gte": "2026-05-01",
                    "mode": "date"
                }
            }
        }
    ]
}

base_params = {
    "filter": json.dumps(filter_query),
    "limit": 1000,     # large page size to minimize round-trips
    "select": "data.irn",   # minimal payload - just need to count, not read records
}

# --- Step 3: page through, tallying counts only ---
headers = {"Authorization": bearer}
next_search_value = None
page_number = 1
total_records = 0

while True:
    if next_search_value is None:
        resp = requests.get(
            f"{EMU_BASE_URL}/{EMU_TENANT}/ecatalogue",
            headers=headers,
            params=base_params,
            timeout=30,
        )
    else:
        resp = requests.get(
            f"{EMU_BASE_URL}/{EMU_TENANT}/ecatalogue",
            headers={**headers, "Next-Search": next_search_value},
            params={"limit": base_params["limit"], "select": base_params["select"]},
            timeout=30,
        )

    resp.raise_for_status()
    data = resp.json()
    matches = data.get("matches", [])
    total_records += len(matches)

    print(f"Page {page_number}: got {len(matches)} records (running total: {total_records})")

    next_search_value = resp.headers.get("Next-Search")
    if not next_search_value:
        print("No Next-Search header - this was the last page.")
        break

    page_number += 1

print(f"\nDone. Total pages: {page_number}, total matching records: {total_records}")