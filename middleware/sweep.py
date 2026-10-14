"""
sweep.py
Safety net for the upload workflow. Finds NetX assets imported recently that
still have no IRN, works out each one's accession number from its file name,
asks EMu which catalogue record has that accession number, and - only when
EXACTLY ONE record matches - sets the IRN (and Accession Number) on the asset.

    python -m middleware.sweep                 # dry run: log what it WOULD do
    python -m middleware.sweep --apply         # actually write to NetX
    python -m middleware.sweep --days 30       # look back further (default 14)

File name -> accession number: the extension is dropped, then one trailing
'_<digits>' suffix (the book / multi-image convention) is removed, so
'2019.123.4_001.jpg' -> '2019.123.4'. This mirrors the EMuAccessionFromFilename
and EMuIrnFromFilename valuelookups in netx-config-files/syncedMetadata.xml;
this job catches anything those did not (EMu record imported after the upload,
a lookup that failed, etc.). Anything it cannot place is logged and left alone:

    no EMu record  -> the record may not exist in EMu yet; retried next sweep
    several records -> accession numbers are not unique in EMu; fix by hand

Only assets imported within --days are examined, so the legacy assets that
lack an IRN are never touched. Safe to run repeatedly (e.g. hourly): once an
asset has an IRN it drops out of the search.
"""
import argparse
import logging
import os
import sys
from pathlib import Path

from . import emu_client
from . import netx_client

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 14


def accession_from_basename(basename):
    """'2019.123.4_001' -> '2019.123.4'; names without a '_<digits>' suffix
    are returned unchanged."""
    base = basename.strip()
    head, sep, tail = base.rpartition("_")
    if sep and head and tail.isdigit():
        return head
    return base


def basename_of(asset):
    """The asset's file name without its extension ('' if unknown)."""
    file_data = asset.get("file")
    if isinstance(file_data, dict) and file_data.get("name"):
        return os.path.splitext(file_data["name"])[0]
    # asset name as created in NetX is already without an extension
    return asset.get("name") or ""


def run(days=DEFAULT_DAYS, apply=False):
    """Sweep recent IRN-less assets. Returns a dict of counts."""
    session = netx_client.get_session()

    # A Solr outage makes the search return zero results, not an error.
    if not netx_client.irn_index_is_populated(session):
        raise RuntimeError(
            "NetX returned no assets with an IRN attribute - Solr/index "
            "problem? Aborting the sweep."
        )

    assets = netx_client.find_recent_assets_without_irn(days, session=session)
    counts = {
        "checked": len(assets), "tagged": 0, "no_emu_record": 0,
        "ambiguous": 0, "no_accession": 0, "errors": 0,
    }
    logger.info(
        "%d asset(s) imported in the last %d day(s) have no IRN%s",
        len(assets), days, "" if apply else " (dry run - nothing will be written)",
    )
    if not assets:
        return counts

    emu_headers = emu_client.get_auth_headers()
    lookups = {}  # accession -> sorted list of IRNs

    for asset in assets:
        asset_id = asset.get("id")
        basename = basename_of(asset)
        accession = accession_from_basename(basename) if basename else ""
        if not accession:
            counts["no_accession"] += 1
            logger.warning("Asset %s has no usable file name; skipped", asset_id)
            continue

        if accession not in lookups:
            lookups[accession] = sorted(
                set(emu_client.find_irns_by_accession(accession, headers=emu_headers))
            )
        irns = lookups[accession]

        if not irns:
            counts["no_emu_record"] += 1
            logger.info("Asset %s (%s): no EMu record with accession %r yet", asset_id, basename, accession)
        elif len(irns) > 1:
            counts["ambiguous"] += 1
            logger.warning(
                "Asset %s (%s): accession %r matches %d EMu records %s; not tagged",
                asset_id, basename, accession, len(irns), irns,
            )
        else:
            irn = irns[0]
            if apply:
                try:
                    netx_client.set_asset_attributes(
                        asset_id,
                        {"IRN": [irn], "Accession Number": [accession]},
                        session=session,
                    )
                except netx_client.NetXAPIError:
                    counts["errors"] += 1
                    logger.exception("Asset %s: failed to set IRN %s", asset_id, irn)
                    continue
            counts["tagged"] += 1
            logger.info(
                "Asset %s (%s): %s IRN %s (accession %s)",
                asset_id, basename, "set" if apply else "WOULD set", irn, accession,
            )

    logger.info(
        "Sweep done: %(checked)d checked, %(tagged)d tagged, %(no_emu_record)d no EMu record, "
        "%(ambiguous)d ambiguous, %(no_accession)d no file name, %(errors)d error(s)",
        counts,
    )
    return counts


def _setup_logging():
    log_path = Path(__file__).resolve().parent.parent / "data" / "sweep.log"
    log_path.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
    )


if __name__ == "__main__":
    _setup_logging()
    parser = argparse.ArgumentParser(description="Tag recent IRN-less NetX assets via their accession number.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"only assets imported in the last N days (default {DEFAULT_DAYS})")
    parser.add_argument("--apply", action="store_true",
                        help="write the IRN to NetX (default: dry run)")
    args = parser.parse_args()
    try:
        run(days=args.days, apply=args.apply)
    except Exception:
        logger.exception("Sweep failed")
        sys.exit(1)
