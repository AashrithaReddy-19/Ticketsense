"""TicketSense V2 real-time ticket events over Server-Sent Events (SSE).

An event is only ever relayed to a connected client after two independent
checks: the TicketEvent's own visibility field (customers never receive an
"internal"-only event) and a live re-check that the ticket is still visible
to that specific user under the same tenant/department/role rules the REST
API already enforces (app.services.ticket_visibility). Nothing here is
pushed sub-second — see app.services.events.bridge for the honest,
near-real-time latency this is actually built on. If SSE is disabled or a
connection drops, the existing REST polling the frontend already does is
the correctness fallback, not an afterthought."""
import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import is_customer
from app.core.security import create_sse_token
from app.database import async_session_maker, get_db
from app.dependencies import get_current_user, get_user_from_sse_token
from app.models.user import User
from app.services.events.bus import bus
from app.services.feature_flags import require_feature
from app.services.ticket_visibility import is_ticket_visible

router = APIRouter(prefix="/api/v2/events", tags=["v2-events"])

HEARTBEAT_SECONDS = 20.0
TOKEN_TTL_SECONDS = 120


async def require_flag(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "real_time_events", user, permissions)


@router.post("/token")
async def mint_stream_token(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_flag(db, user)
    token = create_sse_token(user.id, user.tenant_id, TOKEN_TTL_SECONDS)
    return {"token": token, "expires_in": TOKEN_TTL_SECONDS, "poll_interval_seconds": 2.0}


def _sse_message(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def event_stream(request: Request, user: User):
    queue = bus.subscribe(user.tenant_id)
    try:
        yield _sse_message("connected", {"tenant_id": str(user.tenant_id)})
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if is_customer(user.role) and payload["visibility"] not in ("customer", "both"):
                continue
            async with async_session_maker() as db:
                if not await is_ticket_visible(db, user, UUID(payload["ticket_id"])):
                    continue
            yield _sse_message("ticket_updated", {"ticket_id": payload["ticket_id"], "event_type": payload["event_type"]})
    finally:
        bus.unsubscribe(user.tenant_id, queue)


@router.get("/stream")
async def stream(request: Request, token: str = Query(...), db: AsyncSession = Depends(get_db)):
    user = await get_user_from_sse_token(token, db)
    await require_flag(db, user)
    return StreamingResponse(event_stream(request, user), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
