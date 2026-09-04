"""Section 18: translation provider abstraction and its graceful fallback."""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from ai.agents.llm_interface import DeterministicDevelopmentProvider
from app.main import app


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_deterministic_provider_never_fabricates_a_translation():
    provider = DeterministicDevelopmentProvider()
    same_language = asyncio.run(provider.translate("Hello", "en", "en"))
    assert same_language.available and same_language.translated_text == "Hello"

    unavailable = asyncio.run(provider.translate("Hello", "en", "hi"))
    assert unavailable.available is False
    assert unavailable.machine_translated is False
    assert unavailable.translated_text == "Hello", "must return the original text, never a fabricated one"
    assert unavailable.note and "no translation provider" in unavailable.note.lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_message_translation_endpoint_reports_unavailable_without_a_configured_provider():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        customer = await token(client, "customer@demo.com")
        created = await client.post("/api/tickets", headers=auth(customer), json={"subject": "Translation availability check", "description": "The VPN client will not connect from home."})
        ticket_id = created.json()["id"]
        message = await client.post(f"/api/tickets/{ticket_id}/messages", headers=auth(customer), json={"body": "Any update on my ticket?", "visibility": "public"})
        assert message.status_code == 201, message.text
        message_id = message.json()["id"]

        translated = await client.post(f"/api/tickets/{ticket_id}/messages/{message_id}/translate", headers=auth(customer), json={"target_language": "hi"})
        assert translated.status_code == 200, translated.text
        body = translated.json()
        assert body["available"] is False
        assert body["translated_text"] == "Any update on my ticket?"
        assert body["machine_translated"] is False

        # An unavailable translation must not be persisted onto the message.
        messages = await client.get(f"/api/tickets/{ticket_id}/messages", headers=auth(customer))
        posted = next(item for item in messages.json() if item["id"] == message_id)
        assert posted["translated_body"] is None
        assert posted["machine_translated"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_translating_to_the_same_language_is_a_trivial_success():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        customer = await token(client, "customer@demo.com")
        created = await client.post("/api/tickets", headers=auth(customer), json={"subject": "Same language translation check", "description": "The VPN client will not connect from home."})
        ticket_id = created.json()["id"]
        message = await client.post(f"/api/tickets/{ticket_id}/messages", headers=auth(customer), json={"body": "Still no update?", "visibility": "public", "original_language": "en"})
        message_id = message.json()["id"]
        translated = await client.post(f"/api/tickets/{ticket_id}/messages/{message_id}/translate", headers=auth(customer), json={"target_language": "en"})
        assert translated.status_code == 200
        assert translated.json()["available"] is True
        assert translated.json()["translated_text"] == "Still no update?"


@pytest.mark.asyncio(loop_scope="session")
async def test_resolution_translation_requires_a_published_response_and_correct_owner():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        customer = await token(client, "customer@demo.com")
        other_email = f"translation-owner-check-{__import__('uuid').uuid4().hex}@example.test"
        registered = await client.post("/api/auth/register", json={"email": other_email, "password": "Translation-Test-Only-123", "full_name": "Other Customer"})
        created = await client.post("/api/tickets", headers=auth(customer), json={"subject": "Resolution translation check", "description": "The VPN client will not connect from home."})
        ticket_id = created.json()["id"]

        not_yet = await client.post(f"/api/tickets/{ticket_id}/resolution/translate", headers=auth(customer), json={"target_language": "hi"})
        assert not_yet.status_code == 409

        if registered.status_code == 201:
            other_token = await token(client, other_email)
            denied = await client.post(f"/api/tickets/{ticket_id}/resolution/translate", headers=auth(other_token), json={"target_language": "hi"})
            assert denied.status_code == 404
