"""Public invalidations contain no event data; readers refetch authorized APIs."""
import asyncio
import logging

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from starlette.responses import StreamingResponse

from app.config import get_settings
from app.redis_client import get_redis

router = APIRouter(prefix="/discovery", tags=["discovery"])
CHANNEL = f"{get_settings().environment}:discovery:changed"
logger = logging.getLogger(__name__)


async def notify_discovery_change(method: str, path: str, status: int) -> None:
    prefix = get_settings().api_v1_prefix
    relative = path.removeprefix(prefix).strip("/").split("/")[0]
    if method not in {"POST", "PUT", "PATCH", "DELETE"} or not 200 <= status < 300:
        return
    if relative not in {"events", "event-categories"}:
        return
    # Services have committed before returning a successful response.
    # A notification outage must never turn a committed save into an error.
    try:
        await asyncio.wait_for(get_redis().publish(CHANNEL, "changed"), timeout=2)
    except (Exception, asyncio.TimeoutError):
        logger.exception("Discovery notification failed after successful save")


async def discovery_events(redis: Redis):
    async with redis.pubsub() as subscription:
        await subscription.subscribe(CHANNEL)
        # Refresh on every connection, recovering changes missed while offline.
        yield "event: changed\ndata: {}\n\n"
        while True:
            message = await subscription.get_message(
                ignore_subscribe_messages=True, timeout=15
            )
            if message and message["type"] == "message":
                yield "event: changed\ndata: {}\n\n"
            else:
                yield ": heartbeat\n\n"


@router.get("/changes")
async def changes(redis: Redis = Depends(get_redis)):
    return StreamingResponse(
        discovery_events(redis),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
