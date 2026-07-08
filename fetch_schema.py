"""
Fetch and inspect the Catalogue module schema from the emurestapi shim.
Requires a valid token (via test_auth.py logic).
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

EMU_BASE_URL = f"http://[{EMU_HOST}]:{EMU_PORT}"

# --- Step 1: get a fresh token ---
token_resp = requests.post(
    f"{EMU_BASE_URL}/{EMU_TENANT}/tokens",
    json={"username": EMU_USERNAME, "password": EMU_PASSWORD},
    headers={"Content-Type": "application/json", "Prefer": "representation=minimal"},
    timeout=10,
)
token_resp.raise_for_status()
bearer = token_resp.headers["Authorization"]

# --- Step 2: fetch the ecatalogue resource schema ---
schema_resp = requests.get(
    f"{EMU_BASE_URL}/{EMU_TENANT}/resources/ecatalogue",
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