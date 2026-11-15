import logging

from . import netx_db, netx_staging
from .db import get_connection

webhook_logger = logging.getLogger("api.webhook")


def process_clips_event(event_id: str, asset_ids: list[int]):
    """Runs after the 200 has gone back to NetX. Does the work, then records
    in dbo.netx_staging whether it finished or failed."""
    try:
        _lookup_clips(event_id, asset_ids)
    except Exception as exc:
        # Nothing else will catch this: the response was already sent.
        webhook_logger.exception("Event %s: processing failed", event_id)
        _save_result(event_id, error=str(exc))
    else:
        _save_result(event_id)


def _lookup_clips(event_id, asset_ids):
    """Look up the clips in NetX and log them."""
    if not asset_ids:
        webhook_logger.warning("Event %s: no asset ids, nothing to do", event_id)
        return

    if len(asset_ids) > netx_db.MAX_ASSETS:
        webhook_logger.warning(
            "Event %s: %d assets sent, only the first %d will be looked up",
            event_id, len(asset_ids), netx_db.MAX_ASSETS,
        )
        asset_ids = asset_ids[:netx_db.MAX_ASSETS]

    # Own connection: the request is already over, so no Depends here.
    conn = netx_db.get_netx_connection()
    try:
        found = netx_db.get_clips(conn, asset_ids)
    finally:
        conn.close()

    for asset_id, info in found.items():
        webhook_logger.info(
            "Event %s: asset %s (%s) has %d clip(s)",
            event_id, asset_id, info["filename"], len(info["clips"]),
        )
        for clip in info["clips"]:
            webhook_logger.info(
                "Event %s: asset %s clip '%s' %s -> %s",
                event_id, asset_id, clip["title"], clip["start"], clip["end"],
            )

    missing = [i for i in asset_ids if i not in found]
    if missing:
        webhook_logger.warning("Event %s: not found in NetX: %s", event_id, missing)


def _save_result(event_id, error=None):
    """Write done/failed to dbo.netx_staging. Never raises: if the status
    can't be saved, that goes in the log and the row stays 'received'."""
    try:
        conn = get_connection()
        try:
            if error is None:
                netx_staging.mark_done(conn, event_id)
            else:
                netx_staging.mark_failed(conn, event_id, error)
        finally:
            conn.close()
    except Exception:
        webhook_logger.exception("Event %s: could not save status", event_id)