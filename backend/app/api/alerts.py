"""Alert endpoints."""
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import alerts

router = APIRouter()


class TestAlertRequest(BaseModel):
    message: str = "MarketLens test alert"


@router.get("/status", summary="Alert configuration status")
def status():
    return {
        "enabled":             os.environ.get("ALERTS_ENABLED", "false"),
        "min_confidence":      os.environ.get("ALERTS_MIN_CONFIDENCE", "75"),
        "telegram_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")),
    }


@router.post("/test", summary="Send a one-off test alert to Telegram")
def test(req: TestAlertRequest):
    try:
        ok = alerts.send_telegram(f"🔔 {req.message}")
        return {"sent": ok}
    except Exception as e:
        raise HTTPException(500, str(e))
