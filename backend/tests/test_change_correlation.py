"""Coverage for V2 Phase 15 change-aware incident correlation.

Every hypothesis must come from a real, timestamped change row (feature
flag audit, model deployment, or knowledge article edit) that actually
happened within the lookback window before the incident — never a
fabricated or predicted cause, and always carrying the "not a confirmed
cause" note. A department-scoped change in an unrelated department must
never be surfaced as a plausible hypothesis for a different department's
incident.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.security import hash_password
from app.database import async_session_maker
from app.main import app
from app.models.department import Department
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.platform import Incident, Organization
from app.models.user import User
from app.models.v2_governance import FeatureFlag, FeatureFlagAudit, ModelDeployment
from app.services.change_correlation import LOOKBACK_HOURS, correlate_incident_with_recent_changes


async def _tenant():
    suffix = uuid4().hex
    tenant_id, dept_a, dept_b, admin_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with async_session_maker() as db:
        db.add(Organization(id=tenant_id, name=f"Change Correlation Tenant {suffix}", slug=f"change-corr-{suffix}"))
        await db.flush()
        db.add(Department(id=dept_a, tenant_id=tenant_id, name=f"Networking {suffix}"))
        db.add(Department(id=dept_b, tenant_id=tenant_id, name=f"Billing {suffix}"))
        await db.flush()
        db.add(User(id=admin_id, tenant_id=tenant_id, email=f"admin-{suffix}@example.test", full_name="Admin", role="system_admin", public_role="admin", hashed_password=hash_password("x")))
        await db.commit()
    return tenant_id, dept_a, dept_b, admin_id


async def _teardown(tenant_id):
    t = str(tenant_id)
    async with async_session_maker() as db:
        await db.execute(text("DELETE FROM knowledge_base WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM model_deployments WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM feature_flag_audits WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM incidents WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM users WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM departments WHERE tenant_id=:t"), {"t": t})
        await db.execute(text("DELETE FROM organizations WHERE id=:t"), {"t": t})
        await db.commit()


async def _incident(db, tenant_id, department_id, created_at) -> Incident:
    incident = Incident(tenant_id=tenant_id, department_id=department_id, title="VPN failures spike", service="vpn", created_at=created_at)
    db.add(incident)
    await db.flush()
    return incident


@pytest.mark.asyncio(loop_scope="session")
async def test_correlates_a_recent_feature_flag_toggle_within_the_lookback_window():
    tenant_id, dept_a, _, admin_id = await _tenant()
    try:
        now = datetime.now(timezone.utc)
        async with async_session_maker() as db:
            incident = await _incident(db, tenant_id, dept_a, now)
            flag_row = FeatureFlag(key=f"test-flag-{uuid4().hex}", description="test", owner="Test")
            db.add(flag_row); await db.flush()
            db.add(FeatureFlagAudit(tenant_id=tenant_id, flag_id=flag_row.id, action="enabled", created_at=now - timedelta(hours=2)))
            await db.commit()

            hypotheses = await correlate_incident_with_recent_changes(db, incident)
            assert len(hypotheses) == 1
            assert hypotheses[0]["change_type"] == "feature_flag"
            assert hypotheses[0]["hours_before_incident"] == pytest.approx(2.0, abs=0.01)
            assert "not a confirmed cause" in hypotheses[0]["note"].lower()
    finally:
        await _teardown(tenant_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_ignores_a_change_outside_the_lookback_window():
    tenant_id, dept_a, _, admin_id = await _tenant()
    try:
        now = datetime.now(timezone.utc)
        async with async_session_maker() as db:
            incident = await _incident(db, tenant_id, dept_a, now)
            flag_row = FeatureFlag(key=f"test-flag-{uuid4().hex}", description="test", owner="Test")
            db.add(flag_row); await db.flush()
            db.add(FeatureFlagAudit(tenant_id=tenant_id, flag_id=flag_row.id, action="enabled", created_at=now - timedelta(hours=LOOKBACK_HOURS + 1)))
            await db.commit()

            hypotheses = await correlate_incident_with_recent_changes(db, incident)
            assert hypotheses == []
    finally:
        await _teardown(tenant_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_ignores_a_department_scoped_change_in_an_unrelated_department():
    tenant_id, dept_a, dept_b, admin_id = await _tenant()
    try:
        now = datetime.now(timezone.utc)
        async with async_session_maker() as db:
            incident = await _incident(db, tenant_id, dept_a, now)
            db.add(KnowledgeBaseDocument(tenant_id=tenant_id, department_id=dept_b, title="Billing FAQ", content="...", updated_at=now - timedelta(hours=1)))
            await db.commit()

            hypotheses = await correlate_incident_with_recent_changes(db, incident)
            assert hypotheses == []
    finally:
        await _teardown(tenant_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_includes_a_tenant_wide_change_regardless_of_incident_department():
    tenant_id, dept_a, _, admin_id = await _tenant()
    try:
        now = datetime.now(timezone.utc)
        async with async_session_maker() as db:
            incident = await _incident(db, tenant_id, dept_a, now)
            db.add(ModelDeployment(tenant_id=tenant_id, task_type="department_classifier", action="promote", actor_id=admin_id, reason="test promotion", created_at=now - timedelta(hours=5)))
            await db.commit()

            hypotheses = await correlate_incident_with_recent_changes(db, incident)
            assert len(hypotheses) == 1
            assert hypotheses[0]["change_type"] == "model_deployment"
    finally:
        await _teardown(tenant_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_hypotheses_are_sorted_closest_in_time_first():
    tenant_id, dept_a, _, admin_id = await _tenant()
    try:
        now = datetime.now(timezone.utc)
        async with async_session_maker() as db:
            incident = await _incident(db, tenant_id, dept_a, now)
            db.add(ModelDeployment(tenant_id=tenant_id, task_type="a", action="promote", actor_id=admin_id, reason="far", created_at=now - timedelta(hours=48)))
            db.add(ModelDeployment(tenant_id=tenant_id, task_type="b", action="rollback", actor_id=admin_id, reason="near", created_at=now - timedelta(hours=1)))
            await db.commit()

            hypotheses = await correlate_incident_with_recent_changes(db, incident)
            assert len(hypotheses) == 2
            assert hypotheses[0]["hours_before_incident"] < hypotheses[1]["hours_before_incident"]
            assert "task 'b'" in hypotheses[0]["description"]
    finally:
        await _teardown(tenant_id)


async def _token(client, email, password="Demo@123") -> str:
    resp = await client.post("/api/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_change_correlation_endpoint_is_feature_flag_gated_then_works():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {await _token(client, 'sysadmin@demo.com')}"}
        me = await client.get("/api/auth/me", headers=headers)
        tenant_id = me.json()["tenant_id"]

        async with async_session_maker() as db:
            incident = Incident(tenant_id=tenant_id, title="Live smoke incident", service="vpn")
            db.add(incident)
            await db.commit()
            incident_id = str(incident.id)

        try:
            gated = await client.get(f"/api/incidents/{incident_id}/change-correlations", headers=headers)
            assert gated.status_code == 404

            override = await client.post(
                "/api/v2/features/change_correlation/overrides", headers=headers,
                json={"scope_type": "tenant", "scope_value": tenant_id, "enabled": True, "rollout_percentage": 100, "reason": "Change correlation test"},
            )
            assert override.status_code == 201, override.text
            override_id = override.json()["id"]
            try:
                enabled = await client.get(f"/api/incidents/{incident_id}/change-correlations", headers=headers)
                assert enabled.status_code == 200, enabled.text
                assert "hypotheses" in enabled.json()
            finally:
                await client.delete(f"/api/v2/features/change_correlation/overrides/{override_id}", headers=headers)
        finally:
            async with async_session_maker() as db:
                await db.execute(text("DELETE FROM incidents WHERE id=:i"), {"i": incident_id})
                await db.commit()
