"""
Minimal connectivity test for the emurestapi shim.
Confirms the shim is reachable and responding over HTTP —
does NOT attempt authentication yet.
"""
import os
from dotenv import load_dotenv
import requests

load_dotenv()

EMU_HOST = os.getenv("EMU_HOST")
EMU_PORT = os.getenv("EMU_PORT")

# IPv6 literal addresses must be bracketed in a URL
EMU_BASE_URL = f"http://[{EMU_HOST}]:{EMU_PORT}"

print(f"Testing connection to: {EMU_BASE_URL}")

try:
    resp = requests.get(EMU_BASE_URL, timeout=5)
    print(f"Status code: {resp.status_code}")
    print(f"Response headers: {dict(resp.headers)}")
    print(f"Response body (first 500 chars):\n{resp.text[:500]}")
except requests.exceptions.ConnectionError as e:
    print(f"Connection failed: {e}")
except requests.exceptions.Timeout:
    print("Request timed out — port may be filtered rather than closed")