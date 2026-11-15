import requests
import json
import time

from middleware import config, emu_client

EMU_BASE_URL = config.EMU_BASE_URL
EMU_TENANT = config.EMU_TENANT

# --- Step 1: get a fresh token ---
headers = emu_client.get_auth_headers()

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