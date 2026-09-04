from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import async_session_maker
from app.main import app
from app.models.platform import SLAPolicy
from app.services.sla import DEFAULT_RESOLUTION_MINUTES, breach_risk, compute_sla_due_at


def test_breach_risk_unknown_without_a_due_date():
    assert breach_risk(None) == {"status": "unknown", "minutes_remaining": None, "percent_remaining": None}


def test_breach_risk_classifies_on_track_at_risk_and_breached():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    created = now - timedelta(hours=20)
    due = created + timedelta(hours=24)  # 4 hours (16.7%) of the 24h window remain

    on_track = breach_risk(created + timedelta(hours=30), created, now)
    assert on_track["status"] == "on_track"

    at_risk = breach_risk(due, created, now)
    assert at_risk["status"] == "at_risk"
    assert at_risk["percent_remaining"] is not None and at_risk["percent_remaining"] <= 0.2

    breached = breach_risk(now - timedelta(minutes=1), created, now)
    assert breached["status"] == "breached"
    assert breached["percent_remaining"] == 0.0


def test_breach_risk_falls_back_to_absolute_threshold_without_created_at():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert breach_risk(now + timedelta(minutes=30), None, now)["status"] == "at_risk"
    assert breach_risk(now + timedelta(hours=5), None, now)["status"] == "on_track"


@pytest.mark.asyncio(loop_scope="session")
async def test_compute_sla_due_at_uses_documented_default_without_a_configured_policy():
    async with async_session_maker() as db:
        tenant_id = uuid4()  # a tenant with no sla_policies rows at all
        created_at = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        due = await compute_sla_due_at(db, tenant_id, "high", created_at)
        assert due == created_at + timedelta(minutes=DEFAULT_RESOLUTION_MINUTES["high"])


@pytest.mark.asyncio(loop_scope="session")
async def test_ticket_creation_populates_sla_due_at_from_the_seeded_demo_policy():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post("/api/auth/login", data={"username": "customer@demo.com", "password": "Demo@123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        created = await client.post("/api/tickets", headers=headers, json={"subject": "SLA due-date check", "description": "Confirming ticket creation now sets a real sla_due_at."})
        assert created.status_code == 201, created.text
        assert created.json()["sla_due_at"] is not None
        due_at = datetime.fromisoformat(created.json()["sla_due_at"].replace("Z", "+00:00"))
        assert due_at > datetime.now(timezone.utc)
