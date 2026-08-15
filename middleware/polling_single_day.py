"""
polling_single_day.py
Same as polling.py, but pulls just one day's worth of updates via
emu_client.search_modified_on() instead of the open-ended
search_modified_since(). Intended for backfilling/re-running a specific day.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    # Allow running this file directly (e.g. `python middleware/polling_single_day.py`)
    # in addition to `python -m middleware.polling_single_day` - both need to work.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "middleware"

from . import state
from . import emu_client

MODULE = "ecatalogue"  # starting with just Catalogue for now

logger = logging.getLogger(__name__)


def run(date=None):
    """
    date: "YYYY-MM-DD" string for the single day to pull. If omitted, pulls
    the day after this module's last recorded sync date - or, if this module
    has never synced before, state.py's hardcoded default date itself.
    """
    run_at = datetime.now(timezone.utc).isoformat()

    conn = None
    try:
        conn = state.get_connection()

        # Step 1: make sure the database and tables exist
        state.init_db(conn)

        last_sync_date = state.get_last_sync_date(conn, MODULE)
        if date is None:
            if state.has_synced_before(conn, MODULE):
                date = (
                    datetime.strptime(last_sync_date, "%Y-%m-%d") + timedelta(days=1)
                ).strftime("%Y-%m-%d")
            else:
                date = last_sync_date
        logger.info("Last sync date for %s: %s (backfilling %s)", MODULE, last_sync_date, date)

        # Step 3: ask EMu for everything modified on the requested day
        records = emu_client.search_modified_on(MODULE, date)
        logger.info("Found %d record(s) modified on %s", len(records), date)

        # Step 4: filter out anything already synced for its exact modified
        # date. Fetch already-synced IRNs once per distinct date, not once
        # per record.
        distinct_dates = {record.get("AdmDateModified") for record in records}
        synced_by_date = {
            date_modified: state.get_synced_irns_for_date(conn, MODULE, date_modified)
            for date_modified in distinct_dates
        }

        new_records = []
        for record in records:
            irn = record.get("irn")
            date_modified = record.get("AdmDateModified")
            if irn not in synced_by_date[date_modified]:
                new_records.append(record)

        logger.info("%d record(s) remain after filtering already-synced", len(new_records))

        # Step 4: resolve reference fields (e.g. SubGeographyRef_tab -> ethesaurus)
        # to their target-module data before queuing. One shared token for
        # all the lookups - see resolve_references()'s docstring for why.
        if new_records:
            ref_headers = emu_client.get_auth_headers()
            for record in new_records:
                emu_client.resolve_references(record, headers=ref_headers)

        # Step 5: queue each new record for the separate NetX-insert task
        for record in new_records:
            irn = record.get("irn")
            date_modified = record.get("AdmDateModified")
            state.queue_for_netx(conn, MODULE, irn, json.dumps(record), run_at)
            # state.mark_synced(conn, MODULE, irn, date_modified, run_at)

        # Step 6: record the backfilled day as the last successful sync date
        state.update_last_sync_date(conn, MODULE, date, run_at, status="success")

        ### FIRE CODE TO PUSH TO NETX HERE ###
        ######################################

    except Exception:
        logger.exception("Single-day polling run failed for %s on %s", MODULE, date)
        raise
    finally:
        if conn is not None:
            conn.close()


def _setup_logging():
    log_path = Path(__file__).resolve().parent.parent / "data" / "polling.log"
    log_path.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
    )


if __name__ == "__main__":
    import sys

    _setup_logging()
    if len(sys.argv) > 2:
        print("Usage: python -m middleware.polling_single_day [YYYY-MM-DD]")
        sys.exit(1)
    date_arg = sys.argv[1] if len(sys.argv) == 2 else None
    try:
        run(date_arg)
    except Exception as e:
        print(f"Run failed: {e}")
        sys.exit(1)
