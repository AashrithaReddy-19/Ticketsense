"""Coverage for the V2 Phase 14 process mining lab.

Variants and bottlenecks must be computed purely from real, immutable
TicketEvent rows — hand-verified against a known fixture, not just checked
for shape — and a tenant with too little event history must get an honest
insufficient_data run rather than a fabricated one.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import async_session_maker
from app.main import app
from app.models.response_draft import TicketEvent
from app.services.process_mining.analysis import MIN_TICKETS, _percentile, run_process_mining
from test_resolution_policy_and_assignment import make_ticket, scenario  # noqa: F401


async def _event(db, tenant_id, ticket_id, event_type, when):
    db.add(TicketEvent(tenant_id=tenant_id, ticket_id=ticket_id, event_type=event_type, visibility="internal", created_at=when))


def test_percentile_matches_hand_computed_values():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _percentile(values, 0.5) == 30.0
    assert _percentile(values, 0.0) == 10.0
    assert _percentile(values, 1.0) == 50.0


@pytest.mark.asyncio(loop_scope="session")
async def test_insufficient_data_below_minimum_ticket_count(scenario):
    async with async_session_maker() as db:
        ticket = await make_ticket(db, scenario, "Only one ticket", "n/a")
        await _event(db, scenario["tenant_id"], ticket.id, "ticket_submitted", datetime.now(timezone.utc))
        await db.commit()

        run = await run_process_mining(db, scenario["tenant_id"], scenario["engineer_id"])
        await db.commit()

        assert run.status == "insufficient_data"
        assert f"at least {MIN_TICKETS}" in run.insufficiency_reason
        assert run.variants == [] and run.bottlenecks == []


@pytest.mark.asyncio(loop_scope="session")
async def test_completed_run_computes_real_variants_and_bottlenecks_hand_verified(scenario):
    base = datetime.now(timezone.utc)
    async with async_session_maker() as db:
        # 3 tickets follow submitted -> resolved; 2 follow submitted -> escalated -> resolved.
        happy_path_tickets = [await make_ticket(db, scenario, f"Happy {i}", "n/a") for i in range(3)]
        escalated_tickets = [await make_ticket(db, scenario, f"Escalated {i}", "n/a") for i in range(2)]
        await db.flush()

        for i, ticket in enumerate(happy_path_tickets):
            await _event(db, scenario["tenant_id"], ticket.id, "ticket_submitted", base)
            await _event(db, scenario["tenant_id"], ticket.id, "resolved", base + timedelta(seconds=100 + i * 10))
        for i, ticket in enumerate(escalated_tickets):
            await _event(db, scenario["tenant_id"], ticket.id, "ticket_submitted", base)
            await _event(db, scenario["tenant_id"], ticket.id, "escalated", base + timedelta(seconds=500 + i * 10))
            await _event(db, scenario["tenant_id"], ticket.id, "resolved", base + timedelta(seconds=600 + i * 10))
        await db.commit()

        run = await run_process_mining(db, scenario["tenant_id"], scenario["engineer_id"])
        await db.commit()

        assert run.status == "completed"
        assert run.ticket_count_considered == 5
        assert run.event_count_considered == (3 * 2) + (2 * 3)

        variants = {tuple(v["sequence"]): v for v in run.variants}
        happy = variants[("ticket_submitted", "resolved")]
        escalated = variants[("ticket_submitted", "escalated", "resolved")]
        assert happy["ticket_count"] == 3 and happy["percentage"] == pytest.approx(3 / 5)
        assert escalated["ticket_count"] == 2 and escalated["percentage"] == pytest.approx(2 / 5)

        bottlenecks = {(b["from_event_type"], b["to_event_type"]): b for b in run.bottlenecks}
        submitted_to_resolved = bottlenecks[("ticket_submitted", "resolved")]
        assert submitted_to_resolved["sample_size"] == 3
        assert submitted_to_resolved["mean_seconds"] == pytest.approx((100 + 110 + 120) / 3, abs=0.01)
        submitted_to_escalated = bottlenecks[("ticket_submitted", "escalated")]
        assert submitted_to_escalated["sample_size"] == 2
        assert submitted_to_escalated["mean_seconds"] == pytest.approx((500 + 510) / 2, abs=0.01)
        # The escalated path's second leg (escalated -> resolved, ~100s) is a real, distinct pair
        # from the happy path's single leg (submitted -> resolved, ~100-120s) — never conflated.
        escalated_to_resolved = bottlenecks[("escalated", "resolved")]
        assert escalated_to_resolved["sample_size"] == 2


async def _token(client, email, password="Demo@123") -> str:
    resp = await client.post("/api/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_process_mining_endpoints_are_feature_flag_gated_then_work():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {await _token(client, 'sysadmin@demo.com')}"}
        me = await client.get("/api/auth/me", headers=headers)
        tenant_id = me.json()["tenant_id"]

        gated = await client.post("/api/v2/process-mining/runs", headers=headers)
        assert gated.status_code == 404

        override = await client.post(
            "/api/v2/features/process_mining/overrides", headers=headers,
            json={"scope_type": "tenant", "scope_value": tenant_id, "enabled": True, "rollout_percentage": 100, "reason": "Process mining test"},
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]
        run_id = None
        try:
            created = await client.post("/api/v2/process-mining/runs", headers=headers)
            assert created.status_code == 201, created.text
            run_id = created.json()["id"]
            assert created.json()["status"] in ("completed", "insufficient_data")

            listing = await client.get("/api/v2/process-mining/runs", headers=headers)
            assert listing.status_code == 200
            assert any(r["id"] == run_id for r in listing.json()["items"])

            detail = await client.get(f"/api/v2/process-mining/runs/{run_id}", headers=headers)
            assert detail.status_code == 200
        finally:
            await client.delete(f"/api/v2/features/process_mining/overrides/{override_id}", headers=headers)
            if run_id:
                from sqlalchemy import text
                async with async_session_maker() as db:
                    await db.execute(text("DELETE FROM process_mining_runs WHERE id=:i"), {"i": run_id})
                    await db.commit()
