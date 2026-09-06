import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.feature_flags import stable_bucket


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/auth/login",
        data={"username": email, "password": "Demo@123"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_feature_rollout_bucket_is_stable_and_bounded():
    first = stable_bucket("evaluation_lab", "tenant-a", "user-a")
    assert first == stable_bucket("evaluation_lab", "tenant-a", "user-a")
    assert 0 <= first < 100
    assert first != stable_bucket("evaluation_lab", "tenant-a", "user-b")


@pytest.mark.asyncio(loop_scope="session")
async def test_v2_governance_permissions_and_safe_registry_contract():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        auditor = await token(client, "auditor@demo.com")
        customer = await token(client, "customer@demo.com")

        denied = await client.get("/api/v2/features", headers=auth(customer))
        assert denied.status_code == 403
        safe_decision = await client.get("/api/v2/features/evaluation_lab/evaluate", headers=auth(customer))
        assert safe_decision.status_code == 200
        assert set(safe_decision.json()) == {"key", "enabled"}

        flags = await client.get("/api/v2/features", headers=auth(auditor))
        assert flags.status_code == 200
        assert flags.json()["total"] >= 14
        assert all(item["global_default"] is False for item in flags.json()["items"])
        assert (await client.get("/api/v2/models", headers=auth(auditor))).status_code == 200
        assert (await client.get("/api/v2/observability/ai-usage", headers=auth(auditor))).status_code == 200
        assert (await client.get("/api/v2/capability-bundles", headers=auth(auditor))).status_code == 403

        unsafe_reference = await client.post(
            "/api/v2/models",
            headers=auth(admin),
            json={
                "provider_type": "remote",
                "model_identifier": "candidate",
                "immutable_version": "never-created",
                "task_type": "grounded_draft",
                "config_reference": "literal-secret-value",
            },
        )
        assert unsafe_reference.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_tenant_override_and_global_kill_switch_are_server_enforced():
    override_id = None
    kill_switch_changed = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        headers = auth(admin)
        current_user = (await client.get("/api/auth/me", headers=headers)).json()
        try:
            created = await client.post(
                "/api/v2/features/evaluation_lab/overrides",
                headers=headers,
                json={
                    "scope_type": "tenant",
                    "scope_value": current_user["tenant_id"],
                    "enabled": True,
                    "rollout_percentage": 100,
                    "reason": "Automated server-enforcement test",
                },
            )
            assert created.status_code == 201, created.text
            override_id = created.json()["id"]
            enabled = await client.get("/api/v2/features/evaluation_lab/evaluate", headers=headers)
            assert enabled.json()["enabled"] is True

            stopped = await client.patch(
                "/api/v2/features/evaluation_lab",
                headers=headers,
                json={"kill_switch": True, "reason": "Automated emergency-stop test"},
            )
            assert stopped.status_code == 200, stopped.text
            kill_switch_changed = True
            decision = await client.get("/api/v2/features/evaluation_lab/evaluate", headers=headers)
            assert decision.json()["enabled"] is False
            assert decision.json()["reason_code"] == "KILL_SWITCH"
        finally:
            if kill_switch_changed:
                restored = await client.patch(
                    "/api/v2/features/evaluation_lab",
                    headers=headers,
                    json={"kill_switch": False, "reason": "Restore after automated test"},
                )
                assert restored.status_code == 200, restored.text
            if override_id:
                removed = await client.delete(
                    f"/api/v2/features/evaluation_lab/overrides/{override_id}",
                    headers=headers,
                )
                assert removed.status_code == 204, removed.text


@pytest.mark.asyncio(loop_scope="session")
async def test_capability_bundle_separation_of_duties_is_enforced():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        auditor = await token(client, "auditor@demo.com")
        bundles = await client.get("/api/v2/capability-bundles", headers=auth(admin))
        assert bundles.status_code == 200, bundles.text
        operations = next(item for item in bundles.json()["items"] if item["key"] == "operations_admin")
        auditor_user = (await client.get("/api/auth/me", headers=auth(auditor))).json()
        response = await client.post(
            f"/api/v2/capability-bundles/{operations['id']}/assign",
            headers=auth(admin),
            json={"user_id": auditor_user["id"], "reason": "Must be rejected by separation of duties"},
        )
        assert response.status_code == 409

