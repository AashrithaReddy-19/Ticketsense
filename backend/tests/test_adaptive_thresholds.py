import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import async_session_maker
from app.main import app
from app.services.evaluation.threshold_simulation import DecisionRecord, simulate, wilson_interval


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_wilson_interval_matches_known_reference_value():
    # k=8 successes out of n=10 is a commonly-tabulated Wilson interval reference
    # (Newcombe 1998): approximately (0.49, 0.94).
    low, high = wilson_interval(8, 10)
    assert low == pytest.approx(0.4900, abs=0.001)
    assert high == pytest.approx(0.9436, abs=0.001)
    assert low < 0.8 < high


def test_wilson_interval_requires_at_least_one_observation():
    with pytest.raises(ValueError):
        wilson_interval(0, 0)


def test_simulate_hand_computed_fixture():
    records = [
        DecisionRecord(0.90, True, False),
        DecisionRecord(0.95, True, False),
        DecisionRecord(0.85, True, True),   # a false resolution among the covered rows
        DecisionRecord(0.60, False, False),  # below threshold, referred to a human either way
        DecisionRecord(0.99, True, False),
    ]
    result = simulate(records, proposed_threshold=0.8)
    assert result["sample_size"] == 5
    assert result["estimated_coverage"] == pytest.approx(0.8)
    assert result["estimated_referral_rate"] == pytest.approx(0.2)
    assert result["auto_resolved_at_threshold"] == 4
    assert result["historical_false_resolution_rate"] == pytest.approx(0.25)
    assert result["data_sufficient"] is False
    assert len(result["insufficiency_reasons"]) == 2
    assert result["confidence_interval"][0] <= 0.25 <= result["confidence_interval"][1]
    assert result["sensitive_category_override"] is False


def test_simulate_with_no_historical_records():
    result = simulate([], proposed_threshold=0.5)
    assert result["sample_size"] == 0
    assert result["data_sufficient"] is False
    assert result["estimated_coverage"] is None
    assert result["historical_false_resolution_rate"] is None


def test_simulate_flags_sensitive_category_independent_of_sample_size():
    records = [DecisionRecord(0.95, True, False) for _ in range(40)]
    result = simulate(records, proposed_threshold=0.9, category="Payment disputes")
    assert result["sensitive_category_override"] is True
    assert any("sensitive" in reason.lower() for reason in result["insufficiency_reasons"])
    # A large, clean sample is still "data sufficient" on its own terms — sensitivity
    # is reported as a separate, always-on override, never smuggled into the same flag.
    assert result["data_sufficient"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_simulation_requires_flag_and_permission():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        customer = await token(client, "customer@demo.com")

        denied = await client.post("/api/v2/adaptive-thresholds/simulate", headers=auth(customer), json={"proposed_threshold": 0.5})
        assert denied.status_code == 403

        gated = await client.post("/api/v2/adaptive-thresholds/simulate", headers=auth(admin), json={"proposed_threshold": 0.5})
        assert gated.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_simulation_never_writes_to_live_resolution_policy():
    override_id = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        headers = auth(admin)
        current_user = (await client.get("/api/auth/me", headers=headers)).json()
        async with async_session_maker() as db:
            before = await db.scalar(text("SELECT COUNT(*) FROM department_resolution_policies"))
        try:
            enable = await client.post(
                "/api/v2/features/adaptive_thresholds/overrides", headers=headers,
                json={"scope_type": "tenant", "scope_value": current_user["tenant_id"], "enabled": True, "rollout_percentage": 100, "reason": "Adaptive threshold simulation test"},
            )
            assert enable.status_code == 201, enable.text
            override_id = enable.json()["id"]

            response = await client.post("/api/v2/adaptive-thresholds/simulate", headers=headers, json={"proposed_threshold": 0.5})
            assert response.status_code == 201, response.text
            body = response.json()
            assert body["sample_size"] >= 0
            assert isinstance(body["data_sufficient"], bool)
            if body["sample_size"] < 30:
                assert body["data_sufficient"] is False
                assert body["insufficiency_reasons"]

            listing = await client.get("/api/v2/adaptive-thresholds/simulations", headers=headers)
            assert listing.status_code == 200
            assert listing.json()["total"] >= 1
        finally:
            if override_id:
                await client.delete(f"/api/v2/features/adaptive_thresholds/overrides/{override_id}", headers=headers)
            async with async_session_maker() as db:
                after = await db.scalar(text("SELECT COUNT(*) FROM department_resolution_policies"))
                await db.execute(text("DELETE FROM threshold_simulations WHERE created_by = (SELECT id FROM users WHERE email = 'sysadmin@demo.com')"))
                await db.commit()
        assert before == after
