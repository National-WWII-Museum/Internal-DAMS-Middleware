# WW2 Museum EMu → NetX Middleware

Python middleware that syncs collection records between Axiell EMu (Catalogue and Multimedia modules) and NetX (digital asset management system).

---

## Environment Overview

```
C:\ww2-emu-netx\
|
|-- .env
|-- .gitignore
|-- README.md
|
|-- middleware\              <- our reusable code (a Python "package")
|   |-- __init__.py
|   |-- config.py            <- loads .env once; everything else imports from here
|   |-- emu_client.py        <- token fetch, search/filter, pagination logic
|   |-- ...
|
|-- scripts\                 <- one-off / diagnostic scripts
|   |-- get_schema.py
|   |-- get_sample_records.py
|   `-- ...
|
|-- data\                    <- generated output, not source code
```

## Why split it this way

- `middleware/` is the actual product — the code that eventually runs continuously in production (the polling loop, the webhook listener).
- `scripts/` all things you run manually, once in a while, to explore or diagnose something. 
- `data/` is output, not input — schema JSON, CSVs,  SQLite state file.

---

## Architecture

```
┌─────────────────┐         REST/HTTP          ┌──────────────────┐
│  Middleware VM  │ ───────────────────────►   │     EMu VM       │
│  (Windows)      │   emurestapi shim (8084)   │  (Ubuntu 20.04)  │
│                 │ ◄───────────────────────   │                  │
│  Python script  │      Mason+JSON            │  emurestapi      │
│  (this repo)    │                            │  → Texpress DB   │
└─────────────────┘                            └──────────────────┘
        │   ▼
        │   │
        ▼   │
┌─────────────────┐
│      NetX       │
│  (DAM system)   │
└─────────────────┘
```

- **emurestapi** is a Scala-based REST shim sitting in front of Texpress (EMu's database engine). It returns **Mason+JSON** — a hypermedia-flavored JSON format, not plain REST JSON.
- The shim is **multi-tenant** — one shim instance can serve multiple EMu environments, distinguished by a `{tenant}` name in the URL path (e.g. `/emutest/tokens`). Tenant name is defined server-side in `restapi/conf/tenants.conf` and doesn't necessarily match the instance name.

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
EMU_HOST=            # raw IPv4 address of the EMu VM (DNS hostname will be needed)
EMU_PORT=8084        # emurestapi shim port
EMU_TENANT=          # tenant name from tenants.conf — confirm, do not assume it matches instance name
EMU_USERNAME=        # EMu user credentials for REST API auth
EMU_PASSWORD=        #
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
    "renew": true       // optional
}
```

- Success returns **201** with the token in both the JSON response body and the `Authorization` response header.
- The token is a JWT with a per-tenant configurable expiry (default ~30 min), reset on each valid request by default (`renew: true`).
- Subsequent requests must include `Authorization: Bearer {token}`.

---


## Planned Sync Approach

1. Poll EMu for Catalogue/Multimedia records where `AdmDateModified` is newer than the last successful sync run.
2. Fetch relevant fields for each changed record.
3. Push relevant data/assets to NetX.
4. Record the new "last successful sync" timestamp/state.

**State management:** SQLite is the planned approach for tracking sync state (last run timestamp, per-record status), preferred over a plain text/flat file for production robustness — not yet implemented.

---

## References

- Axiell EMu REST API documentation (see project docs — treated as source of truth for this integration; distinguish EMu 9-specific behavior from generic guidance where docs allow)
- `xmu` community tooling (XML batch workflows, not REST): https://xmu.readthedocs.io