"""
get_record_by_irn.py
Fetches one or more records by irn (GET /{tenant}/{module}/{irn}, no select
filter so every field comes back) and saves each full response to its own
JSON file under data/record_lookups/. Doesn't touch sync_state.db.

Edit MODULE and IRNS below and run.
"""
import json
from pathlib import Path

import requests

from common import config
from common import emu_api

MODULE = "ecatalogue"
IRNS = ["53935"]  

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "record_lookups"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

headers = emu_api.get_auth_headers()

for irn in IRNS:
    resp = requests.get(
        f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/{MODULE}/{irn}",
        headers=headers,
        timeout=30,
    )

    if resp.status_code == 404:
        print(f"{MODULE}/{irn}: not found (404)")
        continue
    resp.raise_for_status()

    record = resp.json().get("data", {})
    record["irn"] = emu_api.extract_irn(record)

    output_path = OUTPUT_DIR / f"{MODULE}_{irn}.json"
    output_path.write_text(json.dumps(record, indent=2))
    print(f"{MODULE}/{irn}: wrote {output_path}")
