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
|-- api\                     <- FastAPI app (staging web UI now; NetX/EMu webhook endpoints later)
|   |-- main.py              <- creates the app, includes the routers
|   |-- routers\             <- one file per concern (ui.py = the records page)
|   |-- templates\, static\  <- Jinja2 + Bulma for the web UI
|
|-- common\                  <- code shared by middleware AND api
|   |-- config.py            <- DB connection settings from .env
|   |-- db.py                <- pyodbc connection + per-request dependency
|   |-- staging.py           <- emu_staging queries used by the web UI
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
- `api/` is the FastAPI service: the read-only staging viewer today, and later the endpoints NetX webhooks call and the ones that return data to EMu. Add a new concern as a new file in `api/routers/` plus one `include_router` line in `api/main.py`. Keep route handlers thin; put real logic in functions they call.
- `common/` holds what both `middleware/` and `api/` need, so the two never drift apart. `middleware/config.py` still has its own copy of the DB settings; moving it onto `common/` is a possible later cleanup.
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
python -m pip install -e .

# Copy the example env file and fill in real values
copy .envExample .env
```

## Command reference

Run everything from the repo root (`C:\Internal-DAMS-Middleware`) with the venv active. Use `python -m ...` rather than bare `pip` / `uvicorn`: on the VM the `.exe` launchers in `.venv\Scripts` can be blocked ("Access is denied"), but `python -m` works. The API and the middleware share the same `.env`. Every job writes a log to `data\<name>.log`.

### Setup (once, or after pulling new dependencies)

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

### Staging web app (API)

```powershell
# start (listens on the network so the team can reach it at http://<vm-ip>:8000/)
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# while developing: restart automatically when files change (don't use as the service)
python -m uvicorn api.main:app --reload
```

Checks: `/health` (app is up), `/health/db` (database reachable), `/` (records table), `/holding.csv` (CSV download), `/logs` (middleware logs, with a warnings/errors filter).

If other machines can't connect, open the port once (admin PowerShell):

```powershell
New-NetFirewallRule -DisplayName "Staging API" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

On the VM it runs as a Windows service via NSSM:

| NSSM field | Value |
|---|---|
| Path | `C:\Internal-DAMS-Middleware\.venv\Scripts\python.exe` |
| Startup directory | `C:\Internal-DAMS-Middleware` |
| Arguments | `-m uvicorn api.main:app --host 0.0.0.0 --port 8000` |

```powershell
nssm start <service-name>
nssm stop <service-name>
nssm restart <service-name>     # after deploying new code
nssm status <service-name>
```

### Full pipeline (what the scheduled task runs)

Polling -> sweep -> routing, in that order. Stops at the first step that fails (exit code 1). Log: `data\pipeline.log`.

```powershell
python -m middleware.pipeline                       # all three steps
python -m middleware.pipeline --skip-polling        # sweep + routing only
python -m middleware.pipeline --days 30             # sweep look-back (default 14)

# poll a fixed EMu modified-date window (both dates inclusive; --to-date optional).
# The watermark is NOT moved - safe for testing and backfills.
python -m middleware.pipeline --from-date 2026-06-03 --to-date 2026-06-05
```

### Individual steps

```powershell
# Polling: EMu records modified since the last run -> emu_staging. Advances the watermark.
python -m middleware.polling

# Polling one day (omit the date for the day after the last synced day). Advances the watermark.
python -m middleware.polling_single_day 2026-06-03
python -m middleware.polling_single_day

# Polling a date range, both ends inclusive. Run directly like this it DOES move the
# watermark to the end date; use pipeline --from-date if you don't want that.
python -m middleware.polling_date_range 2026-06-01 2026-06-05

# Sweep: tag recent NetX assets that have no IRN, via their accession number.
python -m middleware.sweep                          # dry run - logs what it WOULD do
python -m middleware.sweep --apply                  # actually write to NetX
python -m middleware.sweep --days 30 --apply        # look back further (default 14)

# Routing: mark pending/holding rows 'ready' (IRN exists in NetX) or 'holding'.
python -m middleware.routing
```

Run order when doing it by hand: polling, then sweep, then routing. The NetX DSS task then writes metadata for the `ready` rows.

### Re-queueing rows

Sets `status = 'pending'` and clears `synced` / `sync_failed`; the next routing run looks at them again. Pass at least one option; they can be combined.

```powershell
python -m middleware.requeue --failed               # ready rows whose DSS write failed
python -m middleware.requeue --holding              # force a re-check of every holding row
python -m middleware.requeue --missing-file         # every missing_file row
python -m middleware.requeue --irn 229430 118822    # specific IRNs, any status
python -m middleware.routing                        # then re-route
```

### Logs

`data\pipeline.log`, `data\polling.log`, `data\sweep.log`, `data\routing.log`, `data\requeue.log`. Each rotates at about 5 MB and keeps 5 older copies (`pipeline.log.1`, `.2`, ...). The web app's **Logs** page (`/logs`) shows them newest-first with a warnings/errors filter; it reads the folder in `LOG_DIR` (default `data\`).

```powershell
Get-Content data\pipeline.log -Tail 50              # last 50 lines
Get-Content data\pipeline.log -Wait -Tail 20        # follow live
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
LOG_DIR=             # optional, folder the API's Logs page reads; default is the repo's data\ folder
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


## FOlder structure update
- Make a new venv at the repo root, since the old one had webapp/ paths baked in: python -m venv .venv, activate it, then pip install -e .

- Run it from the repo root: uvicorn api.main:app --reload. It used to be app.main:app, so update the NSSM service path and working directory to match when you deploy.