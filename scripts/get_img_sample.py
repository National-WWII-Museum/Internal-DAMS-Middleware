import os
from dotenv import load_dotenv
import requests
import json
import time

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
headers = {"Authorization": bearer}

# --- Step 2: targeted search for just one image record, long timeout ---
filter_query = {
    "AND": [
        {
            "data.MulMimeType": {
                "exact": {"value": "image"}
            }
        }
    ]
}
params = {
    "filter": json.dumps(filter_query),
    "limit": 1,
}

print("Requesting one 'image' record - this may take a while if it requires a full scan...")
start = time.time()
try:
    resp = requests.get(
        f"{EMU_BASE_URL}/{EMU_TENANT}/emultimedia",
        headers=headers,
        params=params,
        timeout=180,  # generous - we're testing whether this is just slow, not stuck
    )
    elapsed = time.time() - start
    print(f"Response received after {elapsed:.1f} seconds. Status: {resp.status_code}")

    if resp.status_code == 200:
        data = resp.json()
        with open("sample_image_record.json", "w") as f:
            json.dump(data.get("matches", []), f, indent=2)
        print(f"Saved {len(data.get('matches', []))} record(s) to sample_image_record.json")
    else:
        print(resp.text[:1000])

except requests.exceptions.ReadTimeout:
    elapsed = time.time() - start
    print(f"Still timed out after {elapsed:.1f} seconds (180s limit). This query is genuinely very slow server-side.")