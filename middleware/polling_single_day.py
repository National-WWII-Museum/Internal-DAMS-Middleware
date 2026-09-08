"""
polling_single_day.py
Same as polling.py, but pulls just one day's worth of updates via
emu_client.search_modified_on().
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import state
from . import emu_client
from . import mapping

MODULE = "ecatalogue"  # starting with just Catalogue for now

logger = logging.getLogger(__name__)


def run(date=None):
    """
    date: "YYYY-MM-DD" string for the single day to pull. If omitted, pulls
    the day after the last recorded sync date - or, if nothing has synced
    before, state.py's hardcoded default date itself.
    """
    run_at = datetime.now(timezone.utc).replace(tzinfo=None)
    rows_processed = 0

    conn = None
    try:
        conn = state.get_connection()

        last_sync_date = state.get_last_sync_date(conn)
        if date is None:
            if state.has_synced_before(conn):
                date = (
                    datetime.strptime(last_sync_date, "%Y-%m-%d") + timedelta(days=1)
                ).strftime("%Y-%m-%d")
            else:
                date = last_sync_date
        logger.info("Last sync date: %s (backfilling %s)", last_sync_date, date)

        # Step 1: ask EMu for everything modified on the requested day
        records = emu_client.search_modified_on(MODULE, date)
        logger.info("Found %d record(s) modified on %s", len(records), date)

        # Step 2: resolve reference fields, map each record to its staging
        # row, and upsert it. One shared token for all the lookups.
        if records:
            ref_headers = emu_client.get_auth_headers()
            for record in records:
                emu_client.resolve_references(record, headers=ref_headers)
                row = mapping.record_to_staging_row(record)
                state.upsert_staging_record(conn, record.get("irn"), row)
                rows_processed += 1

        logger.info("Staged %d record(s)", rows_processed)

        # Step 3: record the backfilled day as the watermark
        state.update_sync_state(
            conn, date, run_at, rows_processed,
            notes=f"ok (single-day {date}): {rows_processed} record(s)",
        )

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
