"""An in-process, per-tenant publish/subscribe fan-out for SSE connections.

This is deliberately in-memory and single-process: it does not fan out
across multiple backend replicas, and a restart drops all subscribers
(they simply reconnect and mint a fresh token). That limitation is
documented rather than hidden — a real multi-replica deployment would need
a shared broker (e.g. Redis pub/sub) in front of this same interface."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from uuid import UUID

_QUEUE_MAXSIZE = 200


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, tenant_id: UUID) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers[str(tenant_id)].add(queue)
        return queue

    def unsubscribe(self, tenant_id: UUID, queue: asyncio.Queue) -> None:
        self._subscribers[str(tenant_id)].discard(queue)

    def subscriber_count(self, tenant_id: UUID) -> int:
        return len(self._subscribers.get(str(tenant_id), ()))

    def publish(self, tenant_id: UUID, payload: dict) -> None:
        for queue in list(self._subscribers.get(str(tenant_id), ())):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # a slow consumer drops a nudge; the client's polling fallback still covers the gap


bus = EventBus()
