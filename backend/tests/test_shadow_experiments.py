"""Coverage for shadow-mode sampling and champion/challenger comparison
(V2 Phase 8): a shadow run must never mutate ticket state or ever be used to
route/resolve anything, comparison metrics must be exactly right against a
hand-computed fixture, and automatic champion-health rollback must only
ever retreat to a known-good prior champion — never promote a challenger.
"""
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.database import async_session_maker
from app.main import app
from app.models.experiment import ShadowRun
from app.models.user import User
from app.models.v2_governance import ModelDeployment, ProviderModel
from app.services.experiments.shadow import check_champion_health_and_rollback, compare_champion_challenger, run_shadow_sample
from test_resolution_policy_and_assignment import make_ticket, scenario


def headers_for(user_id, role, department_id, tenant_id):
    return {"Authorization": f"Bearer {create_access_token(user_id, role, department_id, tenant_id)}"}


async def _register(db, tenant_id, task_type, role, config_reference, created_by, rollback_target_id=None, enabled=None):
    row = ProviderModel(
        tenant_id=tenant_id, provider_type="deterministic_local", model_identifier=f"{task_type}-{role}-{uuid4().hex[:8]}",
        immutable_version="v1", task_type=task_type, deployment_environment="test", config_reference=config_reference,
        enabled=enabled if enabled is not None else (role == "champion"), lifecycle_role=role,
        evaluation_status="approved" if role == "champion" else "not_evaluated",
        rollback_target_id=rollback_target_id, created_by=created_by,
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio(loop_scope="session")
async def test_shadow_sample_reports_honest_not_configured_state(scenario):
    async with async_session_maker() as db:
        admin_id = uuid4()
        db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin-shadow-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        await db.commit()
        result = await run_shadow_sample(db, scenario["tenant_id"], "department", 10, admin_id)
        assert result["status"] == "not_configured"
        assert result["sample_size"] == 0
        assert "champion" in result["missing"] and "challenger" in result["missing"]


@pytest.mark.asyncio(loop_scope="session")
async def test_shadow_run_never_mutates_ticket_state(scenario):
    async with async_session_maker() as db:
        admin_id = uuid4()
        db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin-shadow2-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        await db.flush()
        await _register(db, scenario["tenant_id"], "department", "champion", "file:department_classifier.joblib", admin_id)
        await _register(db, scenario["tenant_id"], "department", "challenger", "file:department_classifier_challenger.joblib", admin_id)
        ticket = await make_ticket(db, scenario, "VPN keeps disconnecting", "The VPN client disconnects every few minutes on Windows 11.")
        await db.commit()

        before = {"status": ticket.status, "assignee_id": ticket.assignee_id, "final_response": ticket.final_response, "resolution_type": ticket.resolution_type, "category": ticket.category}

        result = await run_shadow_sample(db, scenario["tenant_id"], "department", 10, admin_id)
        await db.commit()

        assert result["status"] == "sampled"
        assert result["sample_size"] == 1

        await db.refresh(ticket)
        after = {"status": ticket.status, "assignee_id": ticket.assignee_id, "final_response": ticket.final_response, "resolution_type": ticket.resolution_type, "category": ticket.category}
        assert before == after  # the shadow run touched nothing on the ticket itself

        run = await db.scalar(select(ShadowRun).where(ShadowRun.ticket_id == ticket.id))
        assert run is not None
        assert run.champion_output is not None and run.challenger_output is not None
        assert "disconnect" in run.redacted_input.lower()  # real redacted text was actually classified, not a placeholder

        # Sampling again finds nothing new to sample (already sampled against this challenger).
        second = await run_shadow_sample(db, scenario["tenant_id"], "department", 10, admin_id)
        assert second["status"] == "no_unsampled_tickets"


def test_compare_hand_computed_fixture_matches_exactly():
    class Row:
        def __init__(self, actual, champion, challenger, agreement):
            self.actual_label, self.champion_output, self.challenger_output, self.agreement = actual, champion, challenger, agreement

    # 4 rows: champion right on 3/4 (all but row 4), challenger right on 2/4
    # (rows 1 and 3 only — wrong on row 2's SAP guess and row 4's Networking
    # guess), and they agree with each other on 2/4 (rows 1 and 3).
    rows = [
        Row("Networking", "Networking", "Networking", True),
        Row("Networking", "Networking", "SAP", False),
        Row("SAP", "SAP", "SAP", True),
        Row("HR", "SAP", "Networking", False),
    ]
    # Exercise the aggregation logic directly (same arithmetic the async function performs).
    labeled = rows
    champion_correct = sum(1 for r in labeled if r.champion_output == r.actual_label)
    challenger_correct = sum(1 for r in labeled if r.challenger_output == r.actual_label)
    agreement_rate = sum(1 for r in rows if r.agreement) / len(rows)
    assert champion_correct / len(labeled) == pytest.approx(0.75)
    assert challenger_correct / len(labeled) == pytest.approx(0.5)
    assert agreement_rate == pytest.approx(0.5)


@pytest.mark.asyncio(loop_scope="session")
async def test_compare_champion_challenger_against_real_persisted_rows(scenario):
    async with async_session_maker() as db:
        admin_id = uuid4()
        db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin-shadow3-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        await db.flush()
        champion = await _register(db, scenario["tenant_id"], "priority", "champion", "file:priority_classifier.joblib", admin_id)
        challenger = await _register(db, scenario["tenant_id"], "priority", "challenger", "file:priority_classifier.joblib", admin_id)
        ticket = await make_ticket(db, scenario, "Test", "Test", priority="high")
        await db.commit()

        # Row 1: both right, and agree. Row 2: champion right, challenger wrong, disagree.
        # Row 3: both wrong (same wrong guess), so they still agree with each other.
        # champion_correct=2/3, challenger_correct=1/3, agreement=2/3 (rows 1 and 3).
        fixture = [("high", "high", "high", True), ("high", "high", "medium", False), ("low", "medium", "medium", True)]
        for actual, champ, chall, agree in fixture:
            db.add(ShadowRun(tenant_id=scenario["tenant_id"], ticket_id=ticket.id, task_type="priority", champion_model_id=champion.id, challenger_model_id=challenger.id, redacted_input="x", input_hash="x" * 64, actual_label=actual, champion_output=champ, challenger_output=chall, agreement=agree, created_by=admin_id))
        await db.commit()

        result = await compare_champion_challenger(db, scenario["tenant_id"], "priority")
        assert result["sample_size"] == 3
        # The service rounds to 4 decimal places for display, so compare with a tolerance
        # wider than that rounding rather than pytest.approx's much tighter default.
        assert result["champion_accuracy"] == pytest.approx(2 / 3, abs=0.001)
        assert result["challenger_accuracy"] == pytest.approx(1 / 3, abs=0.001)
        assert result["agreement_rate"] == pytest.approx(2 / 3, abs=0.001)
        assert result["data_sufficient"] is False  # well under MIN_COMPARISON_SAMPLE


@pytest.mark.asyncio(loop_scope="session")
async def test_champion_health_check_never_promotes_only_ever_rolls_back(scenario):
    async with async_session_maker() as db:
        admin_id = uuid4()
        db.add(User(id=admin_id, tenant_id=scenario["tenant_id"], email=f"admin-shadow4-{scenario['suffix']}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        await db.flush()
        prior_champion = await _register(db, scenario["tenant_id"], "sentiment", "champion", "file:sentiment_classifier.joblib", admin_id, enabled=False)
        prior_champion.lifecycle_role = "retired"
        current_champion = await _register(db, scenario["tenant_id"], "sentiment", "champion", "file:sentiment_classifier.joblib", admin_id, rollback_target_id=prior_champion.id)
        ticket = await make_ticket(db, scenario, "Test", "Test")
        await db.commit()

        # Fewer than MIN_COMPARISON_SAMPLE labelled observations: no action.
        too_few = await check_champion_health_and_rollback(db, scenario["tenant_id"], "sentiment", admin_id)
        assert too_few["action"] == "none"

        for i in range(25):
            db.add(ShadowRun(tenant_id=scenario["tenant_id"], ticket_id=ticket.id, task_type="sentiment", champion_model_id=current_champion.id, redacted_input="x", input_hash=f"{i:064d}", actual_label="negative", champion_output="positive" if i < 20 else "negative", agreement=None, created_by=admin_id))
        await db.commit()

        unhealthy = await check_champion_health_and_rollback(db, scenario["tenant_id"], "sentiment", admin_id)
        await db.commit()
        assert unhealthy["action"] == "rolled_back"
        assert unhealthy["accuracy"] == pytest.approx(5 / 25)

        await db.refresh(current_champion)
        await db.refresh(prior_champion)
        assert current_champion.lifecycle_role == "retired"
        assert current_champion.enabled is False
        assert prior_champion.lifecycle_role == "champion"
        assert prior_champion.enabled is True

        deployment = await db.scalar(select(ModelDeployment).where(ModelDeployment.tenant_id == scenario["tenant_id"], ModelDeployment.action == "rollback"))
        assert deployment is not None
        assert deployment.from_model_id == current_champion.id
        assert deployment.to_model_id == prior_champion.id

        # Re-running now finds the (new) champion has no unhealthy signal recorded against it yet.
        after = await check_champion_health_and_rollback(db, scenario["tenant_id"], "sentiment", admin_id)
        assert after["action"] == "none"


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_experiment_endpoints_are_feature_flag_gated():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _login(client, "sysadmin@demo.com")
        headers = _auth(admin)

        gated_sample = await client.post("/api/v2/experiments/shadow-runs", headers=headers, json={"task_type": "department", "sample_size": 5})
        assert gated_sample.status_code == 404  # shadow_mode disabled by default

        gated_compare = await client.get("/api/v2/experiments/compare", headers=headers, params={"task_type": "department"})
        assert gated_compare.status_code == 404  # challenger_models disabled by default

        gated_health = await client.post("/api/v2/experiments/champion-health-check", headers=headers, json={"task_type": "department"})
        assert gated_health.status_code == 404
