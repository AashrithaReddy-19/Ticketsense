from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value


async def login(client, email="agent@demo.com", password="Demo@123"):
    return await client.post("/api/auth/login", data={"username": email, "password": password})


@pytest.mark.asyncio
async def test_login_me_refresh_logout_flow(client):
    response = await login(client)
    assert response.status_code == 200
    token = response.json()["access_token"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "support_agent"
    assert "ticket:read_department" in me.json()["permissions"]
    csrf = client.cookies["ticketsense_csrf"]
    refreshed = await client.post("/api/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert refreshed.status_code == 200
    rotated_csrf = client.cookies["ticketsense_csrf"]
    logged_out = await client.post("/api/auth/logout", headers={"X-CSRF-Token": rotated_csrf})
    assert logged_out.status_code == 204
    assert (await client.post("/api/auth/refresh", headers={"X-CSRF-Token": rotated_csrf})).status_code == 401


@pytest.mark.asyncio
async def test_missing_auth_and_customer_forbidden(client):
    assert (await client.get("/api/tickets")).status_code == 401
    response = await login(client, "customer@demo.com")
    token = response.json()["access_token"]
    assert (await client.get("/api/audit-logs", headers={"Authorization":f"Bearer {token}"})).status_code == 403


@pytest.mark.asyncio
async def test_registration_assigns_customer_permissions_and_lockout(client):
    email=f"lockout-{uuid4()}@example.com"
    registered=await client.post("/api/auth/register",json={"email":email,"full_name":"Lockout Test","password":"Correct-Password-123"})
    assert registered.status_code == 201
    for _ in range(5):
        assert (await login(client,email,"wrong-password")).status_code == 401
    assert (await login(client,email,"Correct-Password-123")).status_code == 429
