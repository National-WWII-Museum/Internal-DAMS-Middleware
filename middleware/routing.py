"""
routing.py
Decide, for every staged EMu record that hasn't been routed yet, whether
NetX already has an asset carrying its IRN.

    status = 'pending'  freshly staged / re-staged by polling.py, not routed yet
    status = 'ready'    NetX has >= 1 asset with this IRN -> the EMuByFilename
                        DSS task writes the metadata
    status = 'holding'  NetX has no asset with this IRN -> parked. Expected to
                        stay here until someone adds the IRN to the asset in
                        NetX; every run re-checks it and promotes it to
                        'ready' as soon as the IRN shows up.

Every pending / holding row is looked up, whether or not it has a file_name
(records for brand-new items have no EMu file yet).

Run it after polling.py and before the NetX DSS auto-task fires:

    python -m middleware.routing

Fail-safe by design: all NetX lookups finish before any status is written,
and rows left 'pending' are picked up by neither DSS task. A failed or
aborted run therefore delays records - it never sends them down the wrong
path.
"""
import logging
import sys
from pathlib import Path

from . import netx_client
from . import state

logger = logging.getLogger(__name__)

_BLANK_IRNS = ("", "NULL")


def run():
    """Route pending/holding rows. Returns a dict of counts."""
    conn = None
    try:
        conn = state.get_connection()

        rows = [
            (irn, status)
            for irn, status in state.get_rows_to_route(conn)
            if str(irn).strip() not in _BLANK_IRNS
        ]
        if not rows:
            logger.info("Nothing to route")
            return {"to_ready": 0, "promoted": 0, "to_holding": 0, "still_holding": 0}
        logger.info("Routing %d row(s)", len(rows))

        session = netx_client.get_session()

        # Canary: a Solr outage makes getAssetsByQuery return zero results
        # rather than an error, which would park every record as 'holding'.
        # Refuse to route at all unless NetX can still find *any* IRN.
        if not netx_client.irn_index_is_populated(session):
            raise RuntimeError(
                "NetX returned no assets with an IRN attribute - Solr/index "
                "problem? Aborting without changing any status."
            )

        found = netx_client.find_existing_irns(
            [irn for irn, _ in rows], session=session
        )

        ready = [irn for irn, _ in rows if str(irn).strip() in found]
        to_holding = [
            irn for irn, status in rows
            if str(irn).strip() not in found and status == state.STATUS_PENDING
        ]
        promoted = sum(
            1 for irn, status in rows
            if status == state.STATUS_HOLDING and str(irn).strip() in found
        )
        still_holding = sum(
            1 for irn, status in rows
            if status == state.STATUS_HOLDING and str(irn).strip() not in found
        )

        # Lookups all succeeded - now write.
        state.set_status(conn, ready, state.STATUS_READY)
        state.set_status(conn, to_holding, state.STATUS_HOLDING)

        counts = {
            "to_ready": len(ready) - promoted,
            "promoted": promoted,
            "to_holding": len(to_holding),
            "still_holding": still_holding,
        }
        logger.info(
            "Routed: %(to_ready)d new -> ready, %(promoted)d holding -> ready, "
            "%(to_holding)d new -> holding, %(still_holding)d still holding",
            counts,
        )
        return counts
    finally:
        if conn is not None:
            conn.close()


def _setup_logging():
    log_path = Path(__file__).resolve().parent.parent / "data" / "routing.log"
    log_path.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
    )


if __name__ == "__main__":
    _setup_logging()
    try:
        run()
    except Exception:
        logger.exception("Routing run failed")
        sys.exit(1)
