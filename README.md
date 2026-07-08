# WW2 Museum EMu → NetX Middleware

Python middleware that syncs collection records from Axiell EMu (Catalogue and Multimedia modules) into NetX (digital asset management system). EMu is the authoritative "golden records" system — data flows **out of** EMu, not into it.

---

## Environment Overview

| Component | Details |
|---|---|
| EMu version | 9.x (exact patch TBD) |
| EMu OS | Ubuntu 20.04.6 LTS |
| EMu instance | `emutest` (non-production) |
| EMu server login | `emu-nwwiim` |
| Middleware VM OS | Windows 10/11 |
| Middleware VM domain | `OVERLORD_DOMAIN` |
| Middleware language | Python 3.14 |
| Integration method | EMu REST API (`emurestapi` shim) |
| Dataset size | 16,000+ records |

EMu is heavily customized per institution — generic Axiell documentation is a starting point only. Hands-on schema exploration against this specific instance is required to confirm field names and behavior.

---

## Architecture

```
┌─────────────────┐         REST/HTTP          ┌──────────────────┐
│  Middleware VM   │ ───────────────────────►   │     EMu VM       │
│  (Windows)       │   emurestapi shim (8084)   │  (Ubuntu 20.04)  │
│                   │ ◄───────────────────────   │                   │
│  Python script    │      Mason+JSON            │  emurestapi       │
│  (this repo)      │                            │  → Texpress DB    │
└─────────────────┘                              └──────────────────┘
        │
        │ (planned)
        ▼
┌─────────────────┐
│      NetX        │
│  (DAM system)     │
└─────────────────┘
```

- **emurestapi** is a Scala-based REST shim sitting in front of Texpress (EMu's underlying object-oriented, non-relational database engine). It returns **Mason+JSON** — a hypermedia-flavored JSON format, not plain REST JSON.
- The shim is **multi-tenant** — one shim instance can serve multiple EMu environments, distinguished by a `{tenant}` name in the URL path (e.g. `/emutest/tokens`). Tenant name is defined server-side in `restapi/conf/tenants.conf` and doesn't necessarily match the instance name.
- No official Python client exists for the EMu REST API. This project uses a thin `requests`-based client written from scratch. (Note: `xmu`, a Smithsonian-developed community tool, exists but targets XML batch export/import workflows, not the REST API — not used here.)

---

## Networking Notes

The EMu VM on this network is **effectively IPv6-only** — `ip -4 addr show` on the EMu VM returns only loopback (`127.0.0.1`), no real IPv4 address on any interface. This was discovered while troubleshooting why the DNS hostname (`prodesx02.ddaymuseum.org`, which only has an A/IPv4 record) wasn't reachable on port 8084, while a raw IPv6 address was.

**Known issue:** The DNS A record for `prodesx02.ddaymuseum.org` appears stale/incorrect — it does not point to a working address for this VM. Not yet escalated to network/DNS admins. Until resolved, this project connects via a raw IPv6 address rather than the hostname.

**IPv6 URL syntax gotcha:** IPv6 literals must be wrapped in brackets when used in a URL with a port, e.g.:
```
http://[2001:db8:abcd:1234::5678]:8084/
```
Without brackets, the colons in the address get misparsed as a port separator.

**Link-local vs. routable addresses:** Be careful not to confuse a link-local address (`fe80::...`) with a routable one. Link-local addresses are scoped to a specific network interface and generally require a `%zoneid` suffix for tools like `ping`/`ssh` to work reliably. `requests` (Python) has so far worked against the link-local address without an explicit zone ID in testing, but this is not fully understood/trusted yet — prefer the routable IPv6 address once confirmed, not the link-local one.

---

## Middleware VM Setup Notes

A few Windows-specific gotchas hit while setting up this VM, documented here so they aren't re-discovered every time:

- **Python must be installed as a genuine CPython install**, not the Microsoft Store version — the Store version installs as an app-execution-alias stub that produces confusing "Access is denied" errors when called from scripts or `pip`.
- **App execution aliases**: Settings → Apps → Advanced app settings → App execution aliases. Only **"Python (default)"** and **"Python install manager"** entries should be toggled on. All other Python-labeled or Store-related aliases should stay off.
- **Bare `pip.exe` is blocked on this VM** (returns "Access is denied") even with correct file permissions and no AppLocker policy in effect — root cause not fully identified (likely EDR/endpoint protection, unconfirmed). **Workaround: always invoke pip via `python -m pip ...`**, never bare `pip`. This applies both at the system level and inside virtual environments on this specific VM.
- **PowerShell script execution is disabled by default**, which blocks venv activation (`Activate.ps1`). Fixed once via:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```

---

## Local Dev Setup

```powershell
# Clone / navigate to project directory
cd C:\ww2-emu-netx

# Create virtual environment
python -m venv .venv

# Activate it
.venv\Scripts\Activate.ps1

# Install dependencies (use -m pip, not bare pip, on this VM)
python -m pip install requests python-dotenv

# Copy the example env file and fill in real values
copy .env.example .env
```

## `.env` Configuration

This project reads configuration from a `.env` file (never committed — see `.gitignore`).

```
EMU_HOST=            # raw IPv6 address of the EMu VM (DNS hostname currently unreliable — see Networking Notes)
EMU_PORT=8084        # emurestapi shim port (confirm against restapi.conf if changed from default)
EMU_TENANT=          # tenant name from tenants.conf — confirm, do not assume it matches instance name
EMU_USERNAME=        # EMu user credentials for REST API auth
EMU_PASSWORD=
```

---

## Authentication

The EMu REST API uses JWT Bearer tokens. There is no pre-issued API key — a token must be requested per session:

```
POST /{tenant}/tokens
Content-Type: application/json

{
    "username": "...",
    "password": "...",
    "timeout": 30,      // optional, minutes
    "renew": true        // optional
}
```

- Success returns **201** with the token in both the JSON response body and the `Authorization` response header.
- The token is a JWT with a per-tenant configurable expiry (default ~30 min), reset on each valid request by default (`renew: true`).
- Subsequent requests must include `Authorization: Bearer {token}`.

**Status: not yet confirmed working end-to-end.** Shim connectivity is confirmed (returns `401 Unauthorized` on an unauthenticated request, meaning the shim is alive and reachable). Actual login with real credentials has not yet been tested/confirmed as of this writing.

---

## Key EMu Fields of Interest

| Field | Module | Purpose |
|---|---|---|
| `irn` | Catalogue / Multimedia | Internal Record Number — the reliable unique identifier |
| `TitMainTitle` | Catalogue | Object title |
| `TitObjectCategory` | Catalogue | Object category/type |
| `AdmDateModified` | Catalogue / Multimedia | Last modified timestamp — used to drive incremental sync |
| `MulMultiMediaRef_tab` | Catalogue | Reference(s) to linked Multimedia records |
| `AdmPublishWebNoPassword` | Catalogue | Web publish flag — governs what's safe to sync externally |

**Note on field names:** EMu is heavily customized per institution. Field names above are believed correct for this instance but should be verified against actual API responses / schema endpoints (`resources/ecatalogue`, `resources/emultimedia`) before being relied upon in production sync logic.

**Note on `_tab` suffix:** Indicates a repeatable field group (nested table) in Texpress's object-oriented data model — not a simple scalar field. Expect an array in the JSON response.

---

## Planned Sync Approach

1. Poll EMu for Catalogue/Multimedia records where `AdmDateModified` is newer than the last successful sync run.
2. Fetch relevant fields for each changed record.
3. Push relevant data/assets to NetX.
4. Record the new "last successful sync" timestamp/state.

**State management:** SQLite is the planned approach for tracking sync state (last run timestamp, per-record status), preferred over a plain text/flat file for production robustness — not yet implemented.

---



---

## References

- Axiell EMu REST API documentation (see project docs — treated as source of truth for this integration; distinguish EMu 9-specific behavior from generic guidance where docs allow)
- `xmu` community tooling (XML batch workflows, not REST): https://xmu.readthedocs.io