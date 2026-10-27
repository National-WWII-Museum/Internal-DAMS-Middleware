"""
NetX webhook: when an asset arrives in NetX, promote its staging row from
'holding' to 'ready' straight away instead of waiting for the next routing run.

    asset id (from the event) -> NetX asset -> accession number
    -> the ONE staging row with that accession -> 'holding' becomes 'ready'

The accession number comes from the asset's Accession Number attribute, or
from its file name when that is still blank (same rules as sweep.py), since
a brand-new asset may not have its attributes filled in yet.

Safe to fire early, late or repeatedly: anything it can't place (no accession,
no match, several matches, row not 'holding') is logged and left alone, and
routing.py still picks those rows up on its normal schedule.

Every event is logged to data/webhook.log (shown on the Logs page). The token
is never logged.
"""
import hmac
import logging
from logging.handlers import RotatingFileHandler

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from common import config, logfiles, staging
from common.db import get_db
from middleware import netx_client
from middleware.sweep import accession_attribute_of, accession_from_basename, basename_of

router = APIRouter()

logger = logging.getLogger("api.webhook")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _log_path = logfiles.log_path("webhook")
    _log_path.parent.mkdir(exist_ok=True)
    _handler = RotatingFileHandler(_log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)


def _token_ok(sent):
    if not config.NETX_WEBHOOK_TOKEN or not isinstance(sent, str):
        return False
    return hmac.compare_digest(sent.encode(), config.NETX_WEBHOOK_TOKEN.encode())


# Plain def (not async): the NetX and DB calls block, so FastAPI runs this in
# its thread pool instead of stalling every other request.
@router.post("/webhook/netx")
def netx_webhook(request: Request, body: dict = Body(...), conn=Depends(get_db)):
    if not _token_ok(body.get("token")):
        logger.warning("Rejected: missing or wrong token (from %s)", request.client.host if request.client else "?")
        raise HTTPException(status_code=401, detail="bad token")

    event = body.get("event") or {}
    event_type = event.get("systemEventType")
    asset_id = event.get("assetId")
    tag = f"event {event_type} asset {asset_id} (message {body.get('messageId')})"

    if config.NETX_WEBHOOK_EVENTS and event_type not in config.NETX_WEBHOOK_EVENTS:
        logger.info("%s: ignored event type", tag)
        return {"result": "ignored"}
    if not asset_id:
        logger.warning("%s: no assetId in event", tag)
        return {"result": "no_asset_id"}

    try:
        asset = netx_client.get_asset(asset_id)
    except netx_client.NetXAPIError:
        logger.exception("%s: NetX lookup failed", tag)
        raise HTTPException(status_code=502, detail="NetX lookup failed")
    if asset is None:
        logger.warning("%s: asset not found in NetX", tag)
        return {"result": "asset_not_found"}

    basename = basename_of(asset)
    accession = accession_attribute_of(asset) or (accession_from_basename(basename) if basename else "")
    if not accession:
        logger.info("%s: no accession number (file %r)", tag, basename)
        return {"result": "no_accession"}

    rows = staging.find_by_accession(conn, accession)
    if not rows:
        logger.info("%s: accession %r not in staging", tag, accession)
        return {"result": "no_match", "accession": accession}
    if len(rows) > 1:
        logger.warning("%s: accession %r matches %d staging rows %s; not changed", tag, accession, len(rows), rows)
        return {"result": "ambiguous", "accession": accession}

    irn, status = rows[0]
    if status != "holding":
        logger.info("%s: accession %r -> IRN %s is %r, not holding; left alone", tag, accession, irn, status)
        return {"result": "not_holding", "accession": accession, "irn": irn, "status": status}

    if staging.promote_holding_to_ready(conn, irn):
        logger.info("%s: accession %r -> IRN %s promoted holding -> ready", tag, accession, irn)
        return {"result": "promoted", "accession": accession, "irn": irn}
    logger.info("%s: accession %r -> IRN %s changed status before the update; left alone", tag, accession, irn)
    return {"result": "not_holding", "accession": accession, "irn": irn}
