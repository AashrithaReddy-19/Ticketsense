"""Regression coverage for the Admin Engineer-management specialization display bug:
GET /admin/engineers and GET /workloads/engineers previously read the legacy, unpopulated
engineer_specializations table instead of the seeded engineer_skills table, so every
engineer showed "Not specified" regardless of their real, seeded specialization."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


SEEDED_SPECIALIZATIONS = {
    "agent@demo.com": "VPN Engineer",
    "sap.engineer@demo.com": "SAP Engineer",
    "payment.engineer@demo.com": "Payment Engineer",
    "network.engineer@demo.com": "Network Engineer",
    "hr.engineer@demo.com": "HR Systems Engineer",
    "cloud.engineer@demo.com": "Cloud Engineer",
    "general.engineer@demo.com": "General Support Engineer",
}


@pytest.mark.asyncio(loop_scope="session")
async def test_seeded_engineer_specializations_and_skill_levels_are_returned():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        response = await client.get("/api/admin/engineers", headers=auth(admin))
        assert response.status_code == 200, response.text
        by_email = {row["email"]: row for row in response.json()}
        for email, expected_specialization in SEEDED_SPECIALIZATIONS.items():
            assert email in by_email, f"seeded engineer {email} missing from /admin/engineers"
            row = by_email[email]
            assert row["specializations"] != [], f"{email} shows no specialization (regression)"
            assert any(expected_specialization.lower() in name.lower() for name in row["specializations"])
            assert row["skills"], f"{email} is missing structured skill-level data"
            assert all(skill["skill_level"] in {"none", "basic", "intermediate", "advanced", "expert"} for skill in row["skills"])

        # The seed marks each of these as the engineer's sole/primary specialization.
        agent_row = by_email["agent@demo.com"]
        primary_skills = [skill for skill in agent_row["skills"] if skill["is_primary"]]
        assert primary_skills and primary_skills[0]["specialization"] == "VPN Engineer"
        assert primary_skills[0]["skill_level"] == "expert"


@pytest.mark.asyncio(loop_scope="session")
async def test_admin_engineers_can_be_filtered_by_specialization_and_availability():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")

        sap_only = await client.get("/api/admin/engineers", headers=auth(admin), params={"specialization": "SAP"})
        assert sap_only.status_code == 200, sap_only.text
        emails = {row["email"] for row in sap_only.json()}
        assert "sap.engineer@demo.com" in emails
        assert "network.engineer@demo.com" not in emails

        available_only = await client.get("/api/admin/engineers", headers=auth(admin), params={"available_only": "true"})
        assert available_only.status_code == 200
        assert all(row["is_available"] for row in available_only.json())

        no_match = await client.get("/api/admin/engineers", headers=auth(admin), params={"specialization": "nonexistent-skill-xyz"})
        assert no_match.status_code == 200
        assert no_match.json() == []


@pytest.mark.asyncio(loop_scope="session")
async def test_workload_dashboard_also_reports_real_specializations():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        response = await client.get("/api/workloads/engineers", headers=auth(admin))
        assert response.status_code == 200, response.text
        by_name = {row["name"]: row for row in response.json()}
        vpn_engineer = next((row for row in by_name.values() if "VPN Engineer" in row["specializations"]), None)
        assert vpn_engineer is not None, "no engineer shows the seeded VPN Engineer specialization on the workload dashboard (regression)"


@pytest.mark.asyncio(loop_scope="session")
async def test_admin_engineers_endpoint_requires_user_manage_permission():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        customer = await token(client, "customer@demo.com")
        denied = await client.get("/api/admin/engineers", headers=auth(customer))
        assert denied.status_code == 403
