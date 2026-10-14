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
- `data/` is output, not input — schema JSON, CSVs, logs. (Sync state lives on a SQL Server DB on a different on site VM.)

---



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

DB_HOST=             # SSMS "Server name", incl. instance, e.g. SQL2019-1\NETX
DB_PORT=             # blank for a named instance (SQL Browser resolves it); set only for a fixed TCP port
DB_NAME=EmuStaging   # target database
DB_USER=             # SQL login
DB_PASSWORD=         #
DB_DRIVER=           # optional, default "ODBC Driver 18 for SQL Server" — must be installed on the VM
DB_ENCRYPT=          # optional, default "yes"
DB_TRUST_SERVER_CERT= # optional, default "yes" (internal server, self-signed cert)
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


## Sync Approach

1. Poll EMu (`ecatalogue`) for records where `AdmDateModified` is newer than the last successful sync run.
2. Fetch the mapped fields for each changed record and resolve reference fields (e.g. `SubGeographyRef_tab` → `ethesaurus`).
3. Map each record onto a `dbo.emu_staging` row (`middleware/mapping.py`) and upsert it — one row per `irn`. An already-synced record that changed is re-staged with `synced` / `sync_failed` reset to 0.
4. **Route** (`middleware/routing.py`, run after polling): look up each `pending` / `holding` row's IRN in NetX (batched `getAssetsByQuery`). Every row is looked up, with or without a `file_name` (records for brand-new items have no EMu file yet). IRN found -> `status = 'ready'`; not found -> `status = 'holding'`. Holding rows are re-checked every run and promoted to `ready` as soon as someone puts the IRN on the asset in NetX. An `exists`-IRN canary aborts the run if NetX/Solr returns nothing (a Solr outage returns zero results, not an error).
5. NetX DSS (`netx-config-files/`) runs two tasks off `emu_staging`: `EMuByFilename` (`status = 'ready'`, sets `synced` / `sync_failed` / `synced_at`, deletes finished rows) and `EMuHolding` (`status = 'holding'`, no callbacks - DSS reports success even on a zero-match, so `synced` means nothing for those rows).
6. Record the run in `dbo.sync_state` — each run appends a new row (`id = MAX(id) + 1`); the newest row's `last_sync_date` is the watermark for the next poll.

**Upload workflow (new items):** files are uploaded with NetX I/O and named `<accession number>[_NNN].<ext>` (the `_NNN` suffix is for multi-image records such as books). Two things tag the new asset with its Accession Number and IRN: the on-import `valuelookup` tasks in `netx-config-files/` (accession number from the file name; IRN looked up in `emu_staging` only when exactly one record has that accession number), and `python -m middleware.sweep`, an hourly safety net that finds recently imported assets with no IRN and asks EMu directly (again only when exactly one record matches). Run the sweep without `--apply` first - it logs what it would do. Accession numbers are not unique across EMu, so ambiguous matches are logged and left untagged.

**State management:** both tables live in a remote **MS SQL Server** database (`EmuStaging`), reached via `pyodbc` — `middleware/state.py`, connection built in `middleware/config.py` from the `DB_*` env vars. The schema is **owned and provisioned by the DBA**; this app only reads and writes rows (it does not create or alter tables). `middleware/mapping.WRITE_COLUMNS` and `emu_client.PLACEHOLDER_FIELDS` must stay in sync with the `emu_staging` column list.

---

## References

- Axiell EMu REST API documentation (see project docs — treated as source of truth for this integration; distinguish EMu 9-specific behavior from generic guidance where docs allow)
- `xmu` community tooling (XML batch workflows, not REST): https://xmu.readthedocs.io