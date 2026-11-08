"""
requeue.py
Manually put rows back in the queue: sets status = 'pending' and resets
synced / sync_failed, so the next `python -m middleware.routing` run looks
them at again.

    python -m middleware.requeue --failed              # ready rows whose DSS write failed
    python -m middleware.requeue --holding             # force a re-check of every holding row
    python -m middleware.requeue --irn 229430 118822   # specific IRNs, any status

Options can be combined.
"""
import argparse
import logging
import sys

from . import state
from common.logging_setup import setup_job_logging

logger = logging.getLogger(__name__)


def run(failed=False, holding=False, irns=None):
    """Re-queue the selected rows. Returns {selector: rows re-queued}."""
    counts = {}
    conn = state.get_connection()
    try:
        if failed:
            counts["failed"] = state.requeue_failed(conn)
        if holding:
            counts["holding"] = state.requeue_by_status(conn, state.STATUS_HOLDING)
        if irns:
            counts["irns"] = state.requeue_irns(conn, irns)
    finally:
        conn.close()
    return counts



def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Put staging rows back in the queue (status = 'pending')."
    )
    parser.add_argument("--failed", action="store_true",
                        help="ready rows whose DSS write failed (sync_failed = 1)")
    parser.add_argument("--holding", action="store_true",
                        help="every holding row (forces a re-check outside the schedule)")
    parser.add_argument("--irn", nargs="+", metavar="IRN",
                        help="specific IRNs, whatever their current status")
    args = parser.parse_args(argv)

    if not (args.failed or args.holding or args.irn):
        parser.error("nothing selected - pass --failed, --holding and/or --irn")

    counts = run(
        failed=args.failed,
        holding=args.holding,
        irns=args.irn,
    )
    for selector, n in counts.items():
        logger.info("Re-queued %d row(s) (%s)", n, selector)


if __name__ == "__main__":
    setup_job_logging("requeue")
    try:
        main()
    except Exception:
        logger.exception("Requeue failed")
        sys.exit(1)
