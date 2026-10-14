"""
polling_date_range.py
One-off test script. Same as polling_single_day.py, but pulls every record
modified within a date range (start and end both inclusive) in a single
EMu search.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import config
from . import state
from . import emu_client
from . import mapping

MODULE = "ecatalogue"  # starting with just Catalogue for now

logger = logging.getLogger(__name__)


def search_modified_between(module, start_date, end_date, fields=None, page_size=500, timeout=30):
    """
    Search an EMu module for records with AdmDateModified between start_date
    and end_date ("YYYY-MM-DD", both inclusive), paging through all results.

    Same return shape as emu_client.search_modified_on().
    """
    if fields is None:
        fields = emu_client.PLACEHOLDER_FIELDS

    # end_date is inclusive, so the exclusive upper bound is the day after it
    day_after_end = (
        datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")

    headers = emu_client.get_auth_headers(timeout=timeout)
    select_str = ",".join(fields) if fields else None

    filter_query = {
        "AND": [
            {
                "data.AdmDateModified": {
                    "range": {
                        "gte": start_date,
                        "lt": day_after_end,
                        "mode": "date",
                    }
                }
            }
        ]
    }

    all_records = []
    next_search_value = None
    page_num = 1

    while True:
        params = {"limit": page_size}
        if select_str:
            params["select"] = select_str
        if next_search_value is None:
            params["filter"] = json.dumps(filter_query)
            request_headers = headers
        else:
            request_headers = {**headers, "Next-Search": next_search_value}

        try:
            resp = requests.get(
                f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/{module}",
                headers=request_headers,
                params=params,
                timeout=timeout,
            )
            if resp.status_code != 200:
                logger.error(
                    "EMu returned %s on page %d for module %s: %s",
                    resp.status_code, page_num, module, resp.text[:1000],
                )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            raise emu_client.EMuAPIError(
                f"EMu search failed for module '{module}' on page {page_num}: {e}"
            ) from e
        except ValueError as e:
            raise emu_client.EMuAPIError(
                f"EMu returned an unparseable response for module '{module}' "
                f"on page {page_num}: {e}"
            ) from e

        matches = data.get("matches", [])

        for m in matches:
            record_data = m.get("data", {})
            record_data["irn"] = emu_client.extract_irn(record_data)
            all_records.append(record_data)

        logger.debug("Fetched page %d for %s: %d record(s)", page_num, module, len(matches))

        next_search_value = resp.headers.get("Next-Search")
        if not next_search_value:
            break
        page_num += 1

    return all_records


def run(start_date, end_date):
    """
    start_date, end_date: "YYYY-MM-DD" strings, both inclusive.
    """
    run_at = datetime.now(timezone.utc).replace(tzinfo=None)
    rows_processed = 0

    conn = None
    try:
        conn = state.get_connection()

        last_sync_date = state.get_last_sync_date(conn)
        logger.info(
            "Last sync date: %s (backfilling %s through %s)",
            last_sync_date, start_date, end_date,
        )

        # Step 1: ask EMu for everything modified within the range
        records = search_modified_between(MODULE, start_date, end_date)
        logger.info(
            "Found %d record(s) modified %s through %s",
            len(records), start_date, end_date,
        )

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

        # Step 3: record the last day of the range as the watermark
        state.update_sync_state(
            conn, end_date, run_at, rows_processed,
            notes=f"ok (range {start_date}..{end_date}): {rows_processed} record(s)",
        )

    except Exception:
        logger.exception(
            "Date-range polling run failed for %s, %s through %s",
            MODULE, start_date, end_date,
        )
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
    if len(sys.argv) != 3:
        print("Usage: python -m middleware.polling_date_range YYYY-MM-DD YYYY-MM-DD")
        sys.exit(1)
    start_arg, end_arg = sys.argv[1], sys.argv[2]
    if start_arg > end_arg:
        print(f"Start date {start_arg} is after end date {end_arg}")
        sys.exit(1)
    try:
        run(start_arg, end_arg)
    except Exception as e:
        print(f"Run failed: {e}")
        sys.exit(1)
