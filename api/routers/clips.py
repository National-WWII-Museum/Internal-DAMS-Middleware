import hmac

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from common.db import get_db
from pydantic import BaseModel

from common import netx_staging
from common.clip_events import process_clips_event
from common.config import NETX_WEBHOOK_TOKEN_CLIPS
from common.logging_setup import setup_named_logger


router = APIRouter(prefix="/api")

webhook_logger = setup_named_logger("api.webhook", "webhook")

class NetxEvent(BaseModel):
    assetIds: list[int]
    eventId: str
    eventTime: int
    userId: int
    customActionId: int
    
class NetxWebhook(BaseModel):
    event: NetxEvent
    token: str



@router.post("/webhooks/clips")
def receive_clips_webhook(payload: NetxWebhook, background_tasks: BackgroundTasks, conn=Depends(get_db)):
    if not NETX_WEBHOOK_TOKEN_CLIPS:
        webhook_logger.error("NETX_WEBHOOK_TOKEN_CLIPS is not set in .env")
        raise HTTPException(status_code=503, detail="webhook not configured")
    
    if not hmac.compare_digest(NETX_WEBHOOK_TOKEN_CLIPS, payload.token):
        webhook_logger.warning(
            "Clips webhook %s rejected: bad token", payload.event.eventId
        )
        raise HTTPException(status_code=401, detail="invalid token")

    is_new = netx_staging.record_event(
        conn, payload.event.eventId, payload.event.assetIds, payload.event.userId
    )

    if not is_new:
        webhook_logger.info(
            "Clips webhook %s already received, skipping", payload.event.eventId
        )
        return {"status": "duplicate"}        


    webhook_logger.info(
        "Clips webhook %s for assets %s",
        payload.event.eventId,
        payload.event.assetIds,      
    )

    background_tasks.add_task(
        process_clips_event, payload.event.eventId, payload.event.assetIds
    )
    return {"status": "received"}