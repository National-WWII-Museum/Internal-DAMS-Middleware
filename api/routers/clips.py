from fastapi import APIRouter, Request
from pydantic import BaseModel


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
async def receive_clips_webhook(payload: NetxWebhook):
    webhook_logger.info(
        "Clips webhook %s for assets %s",
        payload.event.eventId,
        payload.event.assetIds,      
    )
    return {"status": "received"}