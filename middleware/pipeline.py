"""
pipeline.py
One command that runs the whole EMu -> NetX staging pipeline in order:

    1. polling   pull EMu records modified since the last run into emu_staging
    2. sweep     tag recent IRN-less NetX assets via their accession number
    3. routing   mark staged rows 'ready' (asset exists) or 'holding'

    python -m middleware.pipeline                 # all three steps
    python -m middleware.pipeline --skip-polling  # sweep + routing only
    python -m middleware.pipeline --days 30       # sweep look-back (default 14)

Order matters: sweep must run before routing so a freshly uploaded asset
has its IRN by the time routing looks for it. The NetX DSS task
(EMuByFilename, daily) then writes metadata for the 'ready' rows.

Stops at the first failing step: later steps are NOT run, the failure is
logged, and the exit code is 1 (Task Scheduler shows the run as failed).
Log: data/pipeline.log. Run from the project folder ("Start in").
"""
import argparse
import logging
import sys
from pathlib import Path

from . import polling, routing, sweep

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


def run(days=sweep.DEFAULT_DAYS, skip_polling=False):
    """Run the steps in order; raises StepFailed on the first failure."""
    if not skip_polling:
        _step("polling", polling.run)
    _step("sweep", lambda: sweep.run(days=days, apply=True))
    _step("routing", routing.run)


def _setup_logging():
    log_path = Path(__file__).resolve().parent.parent / "data" / "pipeline.log"
    log_path.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
    )


if __name__ == "__main__":
    _setup_logging()
    parser = argparse.ArgumentParser(description="Run polling, sweep and routing in order.")
    parser.add_argument("--days", type=int, default=sweep.DEFAULT_DAYS,
                        help=f"sweep look-back in days (default {sweep.DEFAULT_DAYS})")
    parser.add_argument("--skip-polling", action="store_true",
                        help="skip the EMu polling step")
    args = parser.parse_args()
    try:
        run(days=args.days, skip_polling=args.skip_polling)
    except StepFailed as e:
        logger.error("Pipeline STOPPED: step '%s' failed; later steps were not run", e)
        sys.exit(1)
    logger.info("Pipeline finished OK")
