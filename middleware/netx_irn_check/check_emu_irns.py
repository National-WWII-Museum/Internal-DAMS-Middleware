"""
check_emu_irns.py
Pull ecatalogue IRNs from an EMu search (the same search polling uses) and
ask the NetX API whether an asset exists for each one. No DB involved.

Usage (from the repo root, using the main .env):
    python -m middleware.netx_irn_check.check_emu_irns YYYY-MM-DD [--since]

By default checks records modified on that single day; --since checks
everything modified on or after it.
"""
import argparse
import csv
import logging
import time
from datetime import datetime
from pathlib import Path

from .. import emu_client
from .. import netx_client

MODULE = "ecatalogue"
# Only what the report needs - keeps the EMu search light.
EMU_FIELDS = ["data.irn", "data.WebTitle"]
REQUEST_PAUSE = 0.1  # seconds between NetX calls

logger = logging.getLogger(__name__)


def get_emu_records(date, since=False):
    """EMu records modified on `date` (or on/after it when `since`), deduped by IRN."""
    search = emu_client.search_modified_since if since else emu_client.search_modified_on
    records = search(MODULE, date, fields=EMU_FIELDS)

    seen = set()
    unique = []
    for record in records:
        irn = record.get("irn")
        if irn and irn not in seen:
            seen.add(irn)
            unique.append(record)
    return unique


def check_records(records):
    """One result row per EMu record: FOUND / MISSING / DUPLICATE / ERROR."""
    session = netx_client.get_session()

    results = []
    for record in records:
        irn = str(record["irn"])
        row = {
            "irn": irn, "title": record.get("WebTitle") or "", "status": "",
            "match_count": 0, "netx_asset_ids": "", "netx_filenames": "", "error": "",
        }

        try:
            matches = netx_client.find_assets_by_irn(irn, session=session)
            row["match_count"] = len(matches)
            row["netx_asset_ids"] = " | ".join(str(asset.get("id", "")) for asset in matches)
            row["netx_filenames"] = " | ".join(netx_client.get_asset_filename(asset) for asset in matches)

            if len(matches) < 1:
                row["status"] = "MISSING"
            elif len(matches) == 1:
                row["status"] = "FOUND"
            else:
                row["status"] = "DUPLICATE"

        except netx_client.NetXAPIError as err:
            row["status"] = "ERROR"
            row["error"] = str(err)

        logger.info("%-10s%s  %s  %s", row["status"], irn, row["netx_asset_ids"], row["error"])
        results.append(row)

        time.sleep(REQUEST_PAUSE)

    return results


def write_results(results, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, mode="w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[1])
    parser.add_argument("date", help="YYYY-MM-DD - EMu AdmDateModified to search on")
    parser.add_argument(
        "--since", action="store_true",
        help="check everything modified on or after the date, not just that day",
    )
    args = parser.parse_args()
    datetime.strptime(args.date, "%Y-%m-%d")  # fail early on a bad date

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    records = get_emu_records(args.date, since=args.since)
    scope = "since" if args.since else "on"
    logger.info("Found %d EMu IRN(s) modified %s %s", len(records), scope, args.date)
    if not records:
        return

    logger.info("Checking them in NetX (%s)", netx_client.get_rpc_url())
    results = check_records(records)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = Path(__file__).resolve().parent / "results" / f"emu_irn_check_{args.date}_{timestamp}.csv"
    write_results(results, output_path)

    counts = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
    logger.info("\n%d IRNs checked: %s", len(results), summary)
    logger.info("Results written to %s", output_path)


if __name__ == "__main__":
    main()
