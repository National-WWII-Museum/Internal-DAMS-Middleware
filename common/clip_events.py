import logging

from . import netx_db

webhook_logger = logging.getLogger("api.webhook")

def process_clips_event(event_id: str, asset_ids: list[int]):
    """Runs after the 200 has gone back to NetX. Looks up the clips and logs them."""
    try:
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

    except Exception:
        # Nothing else will catch this: the response was already sent.
        webhook_logger.exception("Event %s: clip lookup failed", event_id)