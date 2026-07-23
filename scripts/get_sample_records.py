"""
get_sample_records_multimedia.py (updated)
Pull a diverse sample of real emultimedia records - spread across different
MulMimeType values where possible - to use as example data when building
the field review workbook and data reference for the Multimedia module.

Saves full records to sample_records_multimedia.json for later inspection.
"""
import requests
import json

from middleware import config, emu_client

EMU_BASE_URL = config.EMU_BASE_URL
EMU_TENANT = config.EMU_TENANT

# --- Step 1: get a fresh token ---
headers = emu_client.get_auth_headers()

# --- Step 2: find out what MulMimeType values actually exist ---
probe_params = {
    "limit": 200,
    "select": "data.MulMimeType",
}
probe_resp = requests.get(
    f"{EMU_BASE_URL}/{EMU_TENANT}/emultimedia",
    headers=headers,
    params=probe_params,
    timeout=30,
)
probe_resp.raise_for_status()
probe_data = probe_resp.json()

mime_types_seen = set()
for match in probe_data.get("matches", []):
    mtype = match.get("data", {}).get("MulMimeType")
    if mtype:
        mime_types_seen.add(mtype)

print(f"MulMimeType values seen in first 200 records: {sorted(mime_types_seen)}")

# --- Step 3: pull one or two full records for each mime type found ---
all_samples = []
for mtype in sorted(mime_types_seen):
    filter_query = {
        "AND": [
            {
                "data.MulMimeType": {
                    "exact": {"value": mtype}
                }
            }
        ]
    }
    params = {
        "filter": json.dumps(filter_query),
        "limit": 2,
    }
    try:
        resp = requests.get(
            f"{EMU_BASE_URL}/{EMU_TENANT}/emultimedia",
            headers=headers,
            params=params,
            timeout=60,  # bumped from 30 - some mime types may require a full scan
        )
    except requests.exceptions.ReadTimeout:
        print(f"{mtype}: timed out after 60s - skipping, likely a very large/unindexed match set")
        continue

    if resp.status_code != 200:
        print(f"Skipping {mtype} - status {resp.status_code}")
        continue
    data = resp.json()
    matches = data.get("matches", [])
    print(f"{mtype}: got {len(matches)} sample record(s)")
    all_samples.extend(matches)

# --- Step 4: save everything to a file for review ---
with open("sample_records_multimedia.json", "w") as f:
    json.dump(all_samples, f, indent=2)

print(f"\nSaved {len(all_samples)} total sample records to sample_records_multimedia.json")