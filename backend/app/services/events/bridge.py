"""Bridges durably-committed TicketEvent rows into the in-process EventBus.

Polling the already-existing, already-tenant/visibility-scoped ticket_events
table — rather than hooking every workflow.record_event()/db.commit() call
site directly — means Phase 13 adds zero risk to the heavily-tested
transition/workflow code paths, and it only ever relays events that are
already durably committed, never a pending or later-rolled-back write.

This is a near-real-time bridge, not a sub-second push architecture: events
reach subscribers within one POLL_INTERVAL_SECONDS of being committed. That
latency is stated honestly here and in the API/UI rather than described as
instant. The existing frontend polling interval remains the correctness
fallback if the bridge or a given SSE connection is ever unavailable."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.response_draft import TicketEvent
from app.services.events.bus import bus

POLL_INTERVAL_SECONDS = 2.0


async def poll_once(db: AsyncSession, since: datetime) -> datetime:
    """Publishes every TicketEvent committed strictly after `since`, and
    returns the new high-water mark. Pulled out of the loop below so it can
    be exercised directly in tests without an infinite loop or real sleep."""
    rows = (await db.scalars(
        select(TicketEvent).where(TicketEvent.created_at > since).order_by(TicketEvent.created_at)
    )).all()
    for row in rows:
        bus.publish(row.tenant_id, {
            "ticket_id": str(row.ticket_id),
            "event_type": row.event_type,
            "visibility": row.visibility,
            "created_at": row.created_at.isoformat(),
        })
        since = row.created_at
    return since


async def run_event_bridge(session_factory) -> None:
    since = datetime.now(timezone.utc)
    while True:
        try:
            async with session_factory() as db:
                since = await poll_once(db, since)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # a transient DB hiccup must never crash the bridge; the next poll retries
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
