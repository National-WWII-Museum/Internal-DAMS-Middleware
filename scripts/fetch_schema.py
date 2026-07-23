"""
Fetch and inspect the Catalogue module schema from the emurestapi shim.
"""
import requests
import json

from middleware import config, emu_client

# --- Step 1: get a fresh token ---
bearer = emu_client.get_token()

# --- Step 2: fetch the ecatalogue resource schema ---
schema_resp = requests.get(
    f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/resources/ecatalogue",
    headers={"Authorization": bearer},
    timeout=10,
)

print(f"Status: {schema_resp.status_code}")

if schema_resp.status_code == 200:
    schema = schema_resp.json()
    # Dump full schema to a file for inspection rather than flooding the terminal
    with open("ecatalogue_schema.json", "w") as f:
        json.dump(schema, f, indent=2)
    print("Schema saved to ecatalogue_schema.json")
else:
    print(schema_resp.text[:1000])