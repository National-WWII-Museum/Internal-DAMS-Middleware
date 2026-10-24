"""
pipeline.py
One command that runs the whole EMu -> NetX staging pipeline in order:

    1. polling   pull EMu records modified since the last run into emu_staging
    2. sweep     tag recent IRN-less NetX assets via their accession number
    3. routing   mark staged rows 'ready' (asset exists) or 'holding'

    python -m middleware.pipeline                 # all three steps
    python -m middleware.pipeline --skip-polling  # sweep + routing only
    python -m middleware.pipeline --days 30       # sweep look-back (default 14)
    python -m middleware.pipeline --from-date 2026-06-03 [--to-date 2026-06-03]
        # poll a fixed EMu modified-date window (both inclusive) instead of
        # since-last-run; the watermark is NOT moved. For testing/backfills.

Order matters: sweep must run before routing so a freshly uploaded asset
has its IRN by the time routing looks for it. The NetX DSS task
(EMuByFilename, daily) then writes metadata for the 'ready' rows.

Stops at the first failing step: later steps are NOT run, the failure is
logged, and the exit code is 1 (Task Scheduler shows the run as failed).
Log: data/pipeline.log. Run from the project folder ("Start in").
"""
import argparse
import logging
from logging.handlers import RotatingFileHandler
import sys
from datetime import datetime
from pathlib import Path

from . import polling, polling_date_range, routing, sweep

logger = logging.getLogger(__name__)


class StepFailed(Exception):
    pass


def _step(name, func):
    logger.info("=== %s: start ===", name)
    try:
        result = func()
    except Exception as e:
        logger.exception("%s raised an exception", name)
        raise StepFailed(name) from e
    if result is False:
        raise StepFailed(name)
    logger.info("=== %s: done ===", name)
    return result


def run(days=sweep.DEFAULT_DAYS, skip_polling=False, from_date=None, to_date=None):
    """Run the steps in order; raises StepFailed on the first failure.

    from_date/to_date ("YYYY-MM-DD", inclusive) swap normal polling for a
    fixed-window poll that leaves the watermark alone.
    """
    if skip_polling:
        pass
    elif from_date:
        end = to_date or from_date
        _step(f"polling {from_date}..{end}",
              lambda: polling_date_range.run(from_date, end, update_watermark=False))
    else:
        _step("polling", polling.run)
    _step("sweep", lambda: sweep.run(days=days, apply=True))
    _step("routing", routing.run)


def _setup_logging():
    log_path = Path(__file__).resolve().parent.parent / "data" / "pipeline.log"
    log_path.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")],
    )


if __name__ == "__main__":
    _setup_logging()
    parser = argparse.ArgumentParser(description="Run polling, sweep and routing in order.")
    parser.add_argument("--days", type=int, default=sweep.DEFAULT_DAYS,
                        help=f"sweep look-back in days (default {sweep.DEFAULT_DAYS})")
    parser.add_argument("--skip-polling", action="store_true",
                        help="skip the EMu polling step")
    parser.add_argument("--from-date", metavar="YYYY-MM-DD",
                        help="poll this EMu modified-date window instead of since-last-run "
                             "(watermark not moved)")
    parser.add_argument("--to-date", metavar="YYYY-MM-DD",
                        help="end of the --from-date window, inclusive (default: same day)")
    args = parser.parse_args()
    if args.to_date and not args.from_date:
        parser.error("--to-date needs --from-date")
    for d in (args.from_date, args.to_date):
        if d:
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                parser.error(f"bad date {d!r}, expected YYYY-MM-DD")
    if args.from_date and args.to_date and args.from_date > args.to_date:
        parser.error("--from-date is after --to-date")
    if args.skip_polling and args.from_date:
        parser.error("--skip-polling and --from-date can't be combined")
    try:
        run(days=args.days, skip_polling=args.skip_polling,
            from_date=args.from_date, to_date=args.to_date)
    except StepFailed as e:
        logger.error("Pipeline STOPPED: step '%s' failed; later steps were not run", e)
        sys.exit(1)
    logger.info("Pipeline finished OK")
