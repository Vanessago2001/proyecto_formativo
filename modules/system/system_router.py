from fastapi import APIRouter
from datetime import datetime, timezone

from core.datetime_utils import SYSTEM_TIMEZONE

router = APIRouter(
    prefix="/system",
    tags=["System"]
)

@router.get("/time")
def get_system_time():
    utc_now = datetime.now(timezone.utc)
    local_now = utc_now.astimezone(SYSTEM_TIMEZONE)

    return {
        "utc": utc_now.isoformat(),
        "local": local_now.isoformat(),
        "timezone": str(SYSTEM_TIMEZONE),
        "timestamp": int(utc_now.timestamp())
    }