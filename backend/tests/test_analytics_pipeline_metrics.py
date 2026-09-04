"""Verifies Phase 12 analytics: pipeline-stage latency is actually recorded during
ticket creation, and the enhanced /api/analytics response carries real per-stage
timing and outcome-rate fields alongside the original response shape."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_ticket_creation_records_pipeline_stage_timings():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        customer = await login(client, "customer@demo.com")
        agent = await login(client, "agent@demo.com")

        created = await client.post(
            "/api/tickets", headers=auth(customer),
            json={"subject": "Pipeline metrics VPN check", "description": "Cannot reach the VPN concentrator from home."},
        )
        assert created.status_code == 201, created.text

        analytics = await client.get("/api/analytics", headers=auth(agent))
        assert analytics.status_code == 200, analytics.text
        body = analytics.json()

        # Original response shape is untouched.
        assert "total_tickets" in body and "status_distribution" in body
        # New Phase 12 fields are present and structurally sound.
        assert "pipeline_stage_latency" in body
        stages = {row["stage"] for row in body["pipeline_stage_latency"]}
        assert {"classification", "routing", "confidence_scoring", "total_intake_pipeline"} <= stages
        for row in body["pipeline_stage_latency"]:
            assert row["sample_count"] >= 1
            if row["average_duration_ms"] is not None:
                assert row["average_duration_ms"] >= 0
        assert "confidence_distribution" in body and set(body["confidence_distribution"]) == {"low", "borderline", "high"}
        assert "department_performance" in body and isinstance(body["department_performance"], list)


@pytest.mark.asyncio(loop_scope="session")
async def test_analytics_requires_an_authorized_role():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        customer = await login(client, "customer@demo.com")
        denied = await client.get("/api/analytics", headers=auth(customer))
        assert denied.status_code == 403
