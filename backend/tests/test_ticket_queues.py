import pytest
from httpx import ASGITransport,AsyncClient
from app.main import app

async def token(client,email):
    response=await client.post("/api/auth/login",data={"username":email,"password":"Demo@123"})
    assert response.status_code==200
    return response.json()["access_token"]

@pytest.mark.asyncio(loop_scope="session")
async def test_role_queues_and_system_admin_denial():
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        agent=await token(client,"agent@demo.com"); reviewer=await token(client,"reviewer@demo.com"); lead=await token(client,"teamlead@demo.com"); admin=await token(client,"sysadmin@demo.com")
        assert (await client.get("/api/queues/assigned",headers={"Authorization":f"Bearer {agent}"})).status_code==200
        triage=await client.get("/api/queues/department_triage",headers={"Authorization":f"Bearer {agent}"}); assert triage.status_code==200; assert set(triage.json())=={"items","page","page_size","total","queue_type"}
        assert (await client.get("/api/queues/review",headers={"Authorization":f"Bearer {reviewer}"})).status_code==200
        assert (await client.get("/api/queues/all",headers={"Authorization":f"Bearer {lead}"})).status_code==200
        assert (await client.get("/api/queues/all",headers={"Authorization":f"Bearer {admin}"})).status_code==403

@pytest.mark.asyncio(loop_scope="session")
async def test_customer_cannot_use_staff_queue():
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        customer=await token(client,"customer@demo.com")
        assert (await client.get("/api/queues/all",headers={"Authorization":f"Bearer {customer}"})).status_code==403
