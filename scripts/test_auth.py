"""
Authenticate against the emurestapi shim using username/password.
Requests a JWT token via POST /{tenant}/tokens.
"""
import os
from dotenv import load_dotenv
import requests

load_dotenv()

EMU_HOST = os.getenv("EMU_HOST")
EMU_PORT = os.getenv("EMU_PORT")
EMU_TENANT = os.getenv("EMU_TENANT")       # e.g. "emutest" — CONFIRM against tenants.conf
EMU_USERNAME = os.getenv("EMU_USERNAME")
EMU_PASSWORD = os.getenv("EMU_PASSWORD")

EMU_BASE_URL = f"http://{EMU_HOST}:{EMU_PORT}"
TOKEN_URL = f"{EMU_BASE_URL}/{EMU_TENANT}/tokens"

payload = {
    "username": EMU_USERNAME,
    "password": EMU_PASSWORD,
    # timeout/renew are optional — omitted here to use tenant defaults
}

headers = {
    "Content-Type": "application/json",
    "Prefer": "representation=minimal",
}

print(f"Requesting token from: {TOKEN_URL}")

resp = requests.post(TOKEN_URL, json=payload, headers=headers, timeout=10)

print(f"Status code: {resp.status_code}")

if resp.status_code == 201:
    print("Auth succeeded!")
    print(f"Bearer token (from header): {resp.headers.get('Authorization')}")
    data = resp.json()
    print(f"Token expires (iat/exp): {data['data']['iat']} -> {data['data']['exp']}")
    print(f"User role (gid): {data['data']['gid']}")
else:
    print("Auth failed.")
    print(resp.text[:500])