"""
test_elocations.py
One-off check that the elocations module is reachable: fetches a fresh
EMu token and pulls a single record (irn, LocNwwiimOnExhibit).
"""
import requests

from middleware import config, emu_client

headers = emu_client.get_auth_headers()

resp = requests.get(
    f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/elocations",
    headers=headers,
    params={"select": "irn,LocNwwiimOnExhibit", "limit": 1},
    timeout=30,
)
resp.raise_for_status()
print(resp.json())
