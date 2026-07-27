"""
polling.py
Scheduled entry point - checks EMu for records modified since the last
successful run, processes them, and updates the sync state.
Intended to be run once a day via Windows Task Scheduler.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import state
from . import emu_client

MODULE = "ecatalogue"  # starting with just Catalogue for now

logger = logging.getLogger(__name__)


def run():
    run_at = datetime.now(timezone.utc).isoformat()
    # Set before the try so the except block can tell whether we got far
    # enough to know what watermark to record the failure against.
    last_sync_date = None

    # Every DB/IO touchpoint in this run lives in one try: a failure
    # anywhere means we can't be sure this run completed, so it all counts 
    # as one failed run. mark_synced() commits per-record as
    # it goes, though, so any records that *did* get marked before a later
    # step failed will still be correctly skipped as already-synced on the
    # retry - see step 4 below.
    try:
        # Step 1: make sure the database and tables exist
        state.init_db()

        # Step 2: find out where we left off last time
        last_sync_date = state.get_last_sync_date(MODULE)
        logger.info("Last sync date for %s: %s", MODULE, last_sync_date)

        # Step 3: ask EMu for everything modified since that date
        records = emu_client.search_modified_since(MODULE, last_sync_date)
        logger.info("Found %d record(s) modified since %s", len(records), last_sync_date)

        # Step 4: filter out anything already synced for its exact modified
        # date. Fetch already-synced IRNs once per distinct date, not once
        # per record.
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

        # Step 5: queue each new record for the separate NetX-insert task,
        # and mark it synced. Both are per-record DB writes, so a crash
        # partway through leaves the completed ones in a consistent state
        # (queued + synced together) rather than queued-but-not-synced.
        for record in new_records:
            irn = record.get("irn")
            date_modified = record.get("AdmDateModified")
            state.queue_for_netx(MODULE, irn, json.dumps(record), run_at)
            state.mark_synced(MODULE, irn, date_modified, run_at)

        # Step 6: record todays date if success
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state.update_last_sync_date(MODULE, today, run_at, status="success")
    except Exception as e:
        logger.exception("Polling run failed for %s", MODULE)
        if last_sync_date is None:
            logger.critical(
                "Failed before determining last_sync_date for %s - skipping "
                "sync_state write since there's no known watermark to record",
                MODULE,
            )
            return
        try:
            state.update_last_sync_date(
                MODULE, last_sync_date, run_at, status="error", error=str(e)
            )
        except Exception:
            logger.exception(
                "Additionally failed to record error status to sync_state for %s", MODULE
            )


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
