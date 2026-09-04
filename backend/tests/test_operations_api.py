import pytest
from httpx import ASGITransport,AsyncClient

from app.main import app


async def token(client,email):
    response=await client.post("/api/auth/login",data={"username":email,"password":"Demo@123"})
    assert response.status_code==200
    return response.json()["access_token"]


def auth(value): return {"Authorization":f"Bearer {value}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_team_lead_workloads_are_department_scoped_and_customer_is_denied():
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        lead=await token(client,"teamlead@demo.com");customer=await token(client,"customer@demo.com")
        response=await client.get("/api/workloads/engineers",headers=auth(lead))
        assert response.status_code==200,response.text
        rows=response.json()
        if rows:
            assert all(row["department_id"]==rows[0]["department_id"] for row in rows)
            assert all(0<=row["capacity_percent"] for row in rows)
        assert (await client.get("/api/workloads/engineers",headers=auth(customer))).status_code==403


@pytest.mark.asyncio(loop_scope="session")
async def test_admin_confidence_policy_is_versioned_and_validated():
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        admin=await token(client,"sysadmin@demo.com");customer=await token(client,"customer@demo.com")
        departments=await client.get("/api/admin/departments",headers=auth(admin));assert departments.status_code==200
        department_id=departments.json()[0]["id"]
        invalid=await client.post(f"/api/admin/departments/{department_id}/confidence-policy",headers=auth(admin),json={"low_threshold":.9,"high_threshold":.5,"reason":"invalid order"})
        assert invalid.status_code==422
        created=await client.post(f"/api/admin/departments/{department_id}/confidence-policy",headers=auth(admin),json={"low_threshold":.52,"high_threshold":.81,"reason":"Operations test"})
        assert created.status_code==201,created.text
        current=await client.get(f"/api/admin/departments/{department_id}/confidence-policy",headers=auth(admin))
        assert current.status_code==200 and current.json()["version"]==created.json()["version"]
        assert (await client.get(f"/api/admin/departments/{department_id}/confidence-policy",headers=auth(customer))).status_code==403
