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
EMU_BASE_URL = f"http://{EMU_HOST}:{EMU_PORT}"

# --- Step 1: get a fresh token ---
token_resp = requests.post(
    f"{EMU_BASE_URL}/{EMU_TENANT}/tokens",
    json={"username": EMU_USERNAME, "password": EMU_PASSWORD},
    headers={"Content-Type": "application/json", "Prefer": "representation=minimal"},
    timeout=10,
)
token_resp.raise_for_status()
bearer = token_resp.headers["Authorization"]

# --- Step 2: define the search ---
filter_query = {
    "AND": [
        {
            "data.AdmDateModified": {
                "range": {
                    "gte": "2026-03-01",
                    "mode": "date"
                }
            }
        }
    ]
}

base_params = {
    "filter": json.dumps(filter_query),
    "limit": 1000,
    "select": "irn",
}

# --- Step 3: loop through every page ---
headers = {"Authorization": bearer}
next_search_value = None
page_number = 1
total_records = 0

while True:
    if next_search_value is None:
        # First request: filter/limit/sort go in params
        resp = requests.get(
            f"{EMU_BASE_URL}/{EMU_TENANT}/ecatalogue",
            headers=headers,
            params=base_params,
            timeout=10,
        )
    else:
        # Subsequent requests: still send limit, plus Next-Search header
        resp = requests.get(
            f"{EMU_BASE_URL}/{EMU_TENANT}/ecatalogue",
            headers={**headers, "Next-Search": next_search_value},
            params={"limit": base_params["limit"]},  # keep limit, drop filter/sort
            timeout=10,
        )

    resp.raise_for_status()
    data = resp.json()
    matches = data.get("matches", [])
    total_records += len(matches)

    print(f"Page {page_number}: got {len(matches)} records (status {resp.status_code})")

    next_search_value = resp.headers.get("Next-Search")
    if not next_search_value:
        print("No Next-Search header - this was the last page.")
        break

    page_number += 1

print(f"\nDone. Total pages: {page_number}, total records: {total_records}")