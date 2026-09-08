"""
polling.py
Scheduled entry point - pulls EMu ecatalogue records modified since the
last successful run, maps each into a dbo.emu_staging row, and advances
the sync watermark. Intended to be run once a day.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import state
from . import emu_client
from . import mapping

MODULE = "ecatalogue"  # starting with just Catalogue for now

logger = logging.getLogger(__name__)


def run():
    # naive UTC - the sync_state datetime2 columns carry no tz
    run_at = datetime.now(timezone.utc).replace(tzinfo=None)
    last_sync_date = None
    rows_processed = 0

    conn = None
    try:
        conn = state.get_connection()

        # Step 1: find out where we left off last time
        last_sync_date = state.get_last_sync_date(conn)
        logger.info("Last sync date: %s", last_sync_date)

        # Step 2: ask EMu for everything modified since that date
        records = emu_client.search_modified_since(MODULE, last_sync_date)
        logger.info("Found %d record(s) modified since %s", len(records), last_sync_date)

        # Step 3: resolve reference fields (e.g. SubGeographyRef_tab -> ethesaurus),
        # map each record to its staging row, and upsert it. One shared token
        # for all the lookups - see resolve_references()'s docstring.
        if records:
            ref_headers = emu_client.get_auth_headers()
            for record in records:
                emu_client.resolve_references(record, headers=ref_headers)
                row = mapping.record_to_staging_row(record)
                state.upsert_staging_record(conn, record.get("irn"), row)
                rows_processed += 1

        logger.info("Staged %d record(s)", rows_processed)

        # Step 4: advance the watermark to today on success
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state.update_sync_state(
            conn, today, run_at, rows_processed,
            notes=f"ok: {rows_processed} record(s) modified since {last_sync_date}",
        )

    except Exception as e:
        logger.exception("Polling run failed for %s", MODULE)
        if conn is None or last_sync_date is None:
            logger.critical(
                "Failed before a DB connection / watermark was established - "
                "nothing recorded to sync_state"
            )
            return
        try:
            # keep the old watermark so the next run retries the same window
            state.update_sync_state(
                conn, last_sync_date, run_at, rows_processed,
                notes=f"ERROR after {rows_processed} record(s): {e}",
            )
        except Exception:
            logger.exception("Additionally failed to record error status to sync_state")
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
    _setup_logging()
    run()
