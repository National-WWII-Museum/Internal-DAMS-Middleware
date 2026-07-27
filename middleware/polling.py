"""
polling.py
Scheduled entry point - checks EMu for records modified since the last
successful run, processes them, and updates the sync state.
Intended to be run once a day via Windows Task Scheduler.
"""
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import state
from . import emu_client

MODULE = "ecatalogue"  # starting with just Catalogue for now

# Every fetched record gets appended here, one row per record, regardless of
# whether it was already synced. A separate (not-yet-built) task will read
# this to push records into NetX - this step just captures what EMu returned.
FETCH_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "junk" / "fetched_records.csv"
FETCH_LOG_FIELDS = ["irn", "module", "AdmDateModified", "fetched_at"]

logger = logging.getLogger(__name__)


def _append_records_to_csv(records, path, fetched_at):
    """Append one row per record to the fetch log, writing the header only
    the first time the file is created."""
    if not records:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FETCH_LOG_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for record in records:
            writer.writerow({
                "irn": record.get("irn"),
                "module": MODULE,
                "AdmDateModified": record.get("AdmDateModified"),
                "fetched_at": fetched_at,
            })


def run():
    # Step 1: make sure the database and tables exist
    state.init_db()

    # Step 2: find out where we left off last time
    last_sync_date = state.get_last_sync_date(MODULE)
    logger.info("Last sync date for %s: %s", MODULE, last_sync_date)

    run_at = datetime.now(timezone.utc).isoformat()

    # Step 3: ask EMu for everything modified since that date
    try:
        records = emu_client.search_modified_since(MODULE, last_sync_date)
    except emu_client.EMuAPIError as e:
        logger.error("Fetch from EMu failed for %s: %s", MODULE, e)
        state.update_last_sync_date(
            MODULE, last_sync_date, run_at, status="error", error=str(e)
        )
        return

    logger.info("Found %d record(s) modified since %s", len(records), last_sync_date)

    # Step 4: filter out anything already synced for its exact modified date.
    # Fetch already-synced IRNs once per distinct date, not once per record.
    distinct_dates = {record.get("AdmDateModified") for record in records}
    synced_by_date = {
        date: state.get_synced_irns_for_date(MODULE, date)
        for date in distinct_dates
    }

    new_records = []
    for record in records:
        irn = record.get("irn")
        date_modified = record.get("AdmDateModified")
        if irn not in synced_by_date[date_modified]:
            new_records.append(record)

    logger.info("%d record(s) remain after filtering already-synced", len(new_records))

    # Step 5: log every new record to the fetch CSV, one row each.
    _append_records_to_csv(new_records, FETCH_LOG_PATH, run_at)

    # Step 6: mark each new record as synced.
    for record in new_records:
        state.mark_synced(MODULE, record.get("irn"), record.get("AdmDateModified"), run_at)

    # Step 7: record success and advance last_sync_date to the newest
    # AdmDateModified seen (not just among new_records) - AdmDateModified is
    # date-only, so re-querying from that same date next time and relying on
    # synced_records to dedupe is how same-day records get picked up safely.
    newest_date = max(
        (r.get("AdmDateModified") for r in records if r.get("AdmDateModified")),
        default=last_sync_date,
    )
    state.update_last_sync_date(MODULE, newest_date, run_at, status="success")


def _setup_logging():
    log_path = Path(__file__).resolve().parent.parent / "data" / "polling.log"
    log_path.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
    )


if __name__ == "__main__":
    _setup_logging()
    run()
