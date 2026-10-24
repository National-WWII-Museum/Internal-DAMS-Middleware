"""
requeue.py
Manually put rows back in the queue: sets status = 'pending' and resets
synced / sync_failed, so the next `python -m middleware.routing` run looks
them at again.

    python -m middleware.requeue --failed              # ready rows whose DSS write failed
    python -m middleware.requeue --holding             # force a re-check of every holding row
    python -m middleware.requeue --missing-file        # every missing_file row
    python -m middleware.requeue --irn 229430 118822   # specific IRNs, any status

Options can be combined. Note: a missing_file row with still no file_name is
simply parked as missing_file again by the next routing run - re-queueing
only helps once the row has a file_name (e.g. after EMu is fixed and the
record is re-polled).
"""
import argparse
import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path

from . import state

logger = logging.getLogger(__name__)


def run(failed=False, holding=False, missing_file=False, irns=None):
    """Re-queue the selected rows. Returns {selector: rows re-queued}."""
    counts = {}
    conn = state.get_connection()
    try:
        if failed:
            counts["failed"] = state.requeue_failed(conn)
        if holding:
            counts["holding"] = state.requeue_by_status(conn, state.STATUS_HOLDING)
        if missing_file:
            counts["missing_file"] = state.requeue_by_status(conn, state.STATUS_MISSING_FILE)
        if irns:
            counts["irns"] = state.requeue_irns(conn, irns)
    finally:
        conn.close()
    return counts


def _setup_logging():
    log_path = Path(__file__).resolve().parent.parent / "data" / "requeue.log"
    log_path.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")],
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Put staging rows back in the queue (status = 'pending')."
    )
    parser.add_argument("--failed", action="store_true",
                        help="ready rows whose DSS write failed (sync_failed = 1)")
    parser.add_argument("--holding", action="store_true",
                        help="every holding row (forces a re-check outside the schedule)")
    parser.add_argument("--missing-file", action="store_true", dest="missing_file",
                        help="every missing_file row")
    parser.add_argument("--irn", nargs="+", metavar="IRN",
                        help="specific IRNs, whatever their current status")
    args = parser.parse_args(argv)

    if not (args.failed or args.holding or args.missing_file or args.irn):
        parser.error("nothing selected - pass --failed, --holding, --missing-file and/or --irn")

    counts = run(
        failed=args.failed,
        holding=args.holding,
        missing_file=args.missing_file,
        irns=args.irn,
    )
    for selector, n in counts.items():
        logger.info("Re-queued %d row(s) (%s)", n, selector)


if __name__ == "__main__":
    _setup_logging()
    try:
        main()
    except Exception:
        logger.exception("Requeue failed")
        sys.exit(1)
