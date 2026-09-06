"""Coverage for the V2 Phase 13 real-time ticket events (SSE).

The event bridge only ever relays TicketEvent rows that are already
durably committed — it is a near-real-time poller, not a sub-second push,
and that latency is asserted honestly rather than hidden. The stream
generator must independently re-verify per-event visibility (customer
visibility flag, and live tenant/ownership scoping) before relaying
anything, exactly mirroring the REST timeline endpoint's rules — a
cross-tenant leak or a customer receiving an internal-only event would be
a real security regression, not just a missing feature.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token, create_sse_token, decode_access_token, hash_password
from app.database import async_session_maker
from app.dependencies import get_current_user, get_user_from_sse_token
from app.main import app
from app.models.response_draft import TicketEvent
from app.models.ticket import Ticket
from app.models.user import User
from app.routers.events import event_stream
from app.services.events.bridge import poll_once
from app.services.events.bus import EventBus, bus
from fastapi import HTTPException
from test_resolution_policy_and_assignment import make_ticket, scenario  # noqa: F401


def test_bus_publish_delivers_to_subscribed_tenant_only():
    local_bus = EventBus()
    tenant_a, tenant_b = uuid4(), uuid4()
    queue_a = local_bus.subscribe(tenant_a)
    queue_b = local_bus.subscribe(tenant_b)
    local_bus.publish(tenant_a, {"ticket_id": "x"})
    assert queue_a.get_nowait() == {"ticket_id": "x"}
    assert queue_b.empty()


def test_bus_drops_rather_than_blocks_when_a_subscriber_queue_is_full():
    local_bus = EventBus()
    tenant = uuid4()
    queue = local_bus.subscribe(tenant)
    for i in range(300):
        local_bus.publish(tenant, {"n": i})  # must never raise even past the queue's maxsize
    assert queue.qsize() <= 200


def test_bus_unsubscribe_stops_further_delivery():
    local_bus = EventBus()
    tenant = uuid4()
    queue = local_bus.subscribe(tenant)
    local_bus.unsubscribe(tenant, queue)
    local_bus.publish(tenant, {"n": 1})
    assert queue.empty()


@pytest.mark.asyncio(loop_scope="session")
async def test_poll_once_publishes_real_committed_events_and_advances_watermark(scenario):
    local_bus = EventBus()
    import app.services.events.bridge as bridge_module
    original_bus = bridge_module.bus
    bridge_module.bus = local_bus
    try:
        async with async_session_maker() as db:
            ticket = await make_ticket(db, scenario, "Bridge test ticket", "Something broke")
            since = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.add(TicketEvent(tenant_id=scenario["tenant_id"], ticket_id=ticket.id, event_type="status_changed", visibility="both"))
            await db.commit()

            queue = local_bus.subscribe(scenario["tenant_id"])
            new_since = await poll_once(db, since)
            assert new_since > since
            delivered = queue.get_nowait()
            assert delivered["ticket_id"] == str(ticket.id) and delivered["event_type"] == "status_changed"

            # Re-polling from the new watermark must not re-deliver the same row.
            newer_since = await poll_once(db, new_since)
            assert newer_since == new_since
            assert queue.empty()
    finally:
        bridge_module.bus = original_bus


def test_create_sse_token_round_trips_and_is_marked_type_sse():
    user_id, tenant_id = uuid4(), uuid4()
    token = create_sse_token(user_id, tenant_id, ttl_seconds=60)
    payload = decode_access_token(token)
    assert payload["type"] == "sse"
    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)


def test_expired_sse_token_fails_to_decode():
    token = create_sse_token(uuid4(), uuid4(), ttl_seconds=-1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_current_user_rejects_an_sse_token_as_a_bearer_token(scenario):
    token = create_sse_token(scenario["customer_id"], scenario["tenant_id"], ttl_seconds=60)
    async with async_session_maker() as db:
        with pytest.raises(HTTPException) as exc:
            await get_current_user(token, db)
        assert exc.value.status_code == 401


@pytest.mark.asyncio(loop_scope="session")
async def test_get_user_from_sse_token_rejects_a_normal_access_token(scenario):
    token = create_access_token(scenario["customer_id"], "customer", scenario["department_id"], scenario["tenant_id"])
    async with async_session_maker() as db:
        with pytest.raises(HTTPException) as exc:
            await get_user_from_sse_token(token, db)
        assert exc.value.status_code == 401


@pytest.mark.asyncio(loop_scope="session")
async def test_get_user_from_sse_token_accepts_a_real_sse_token(scenario):
    token = create_sse_token(scenario["customer_id"], scenario["tenant_id"], ttl_seconds=60)
    async with async_session_maker() as db:
        user = await get_user_from_sse_token(token, db)
        assert user.id == scenario["customer_id"]


class FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


@pytest.mark.asyncio(loop_scope="session")
async def test_event_stream_relays_visible_event_and_filters_invisible_ones(scenario):
    async with async_session_maker() as db:
        own_ticket = await make_ticket(db, scenario, "My own ticket", "Cannot log in")
        other_customer = User(id=uuid4(), tenant_id=scenario["tenant_id"], email=f"other-{uuid4().hex}@example.test",
                               full_name="Other Customer", role="customer", public_role="customer", hashed_password=hash_password("x"))
        db.add(other_customer); await db.flush()
        others_ticket = Ticket(tenant_id=scenario["tenant_id"], submitted_by=other_customer.id, department_id=scenario["department_id"],
                                subject="Someone else's ticket", description="n/a", status="ai_processing", priority="medium", sentiment="neutral")
        db.add(others_ticket); await db.flush()
        await db.commit()

        customer = await db.get(User, scenario["customer_id"])
        gen = event_stream(FakeRequest(), customer)
        try:
            first = await gen.__anext__()
            assert "event: connected" in first

            bus.publish(scenario["tenant_id"], {"ticket_id": str(own_ticket.id), "event_type": "internal_note", "visibility": "internal"})  # must be filtered: customer + internal-only
            bus.publish(scenario["tenant_id"], {"ticket_id": str(others_ticket.id), "event_type": "status_changed", "visibility": "both"})  # must be filtered: not this customer's ticket
            bus.publish(scenario["tenant_id"], {"ticket_id": str(own_ticket.id), "event_type": "status_changed", "visibility": "both"})  # must be relayed

            relayed = await asyncio.wait_for(gen.__anext__(), timeout=5)
            assert "event: ticket_updated" in relayed
            assert str(own_ticket.id) in relayed
            assert str(others_ticket.id) not in relayed
        finally:
            await gen.aclose()


async def _token(client, email, password="Demo@123") -> str:
    resp = await client.post("/api/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_stream_token_endpoint_is_feature_flag_gated_then_honest():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {await _token(client, 'sysadmin@demo.com')}"}
        me = await client.get("/api/auth/me", headers=headers)
        tenant_id = me.json()["tenant_id"]

        gated = await client.post("/api/v2/events/token", headers=headers)
        assert gated.status_code == 404

        override = await client.post(
            "/api/v2/features/real_time_events/overrides", headers=headers,
            json={"scope_type": "tenant", "scope_value": tenant_id, "enabled": True, "rollout_percentage": 100, "reason": "Realtime events test"},
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]
        try:
            minted = await client.post("/api/v2/events/token", headers=headers)
            assert minted.status_code == 200, minted.text
            body = minted.json()
            assert body["poll_interval_seconds"] == 2.0  # honestly matches the real bridge poll interval, not a marketing number
            payload = decode_access_token(body["token"])
            assert payload["type"] == "sse"
        finally:
            await client.delete(f"/api/v2/features/real_time_events/overrides/{override_id}", headers=headers)
