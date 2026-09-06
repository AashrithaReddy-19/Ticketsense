"""SSO must report an honest configuration state — never a fabricated
"working" status, and never leak the client secret even if one is set."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app


@pytest.mark.asyncio(loop_scope="session")
async def test_sso_status_reports_honestly_unconfigured_by_default():
    assert settings.oidc_configured is False
    assert settings.saml_configured is False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/auth/sso/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"oidc": {"configured": False, "issuer_url": None}, "saml": {"configured": False}}


@pytest.mark.asyncio(loop_scope="session")
async def test_sso_status_reflects_real_configuration_without_leaking_the_secret(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://idp.example.test")
    monkeypatch.setattr(settings, "oidc_client_id", "client-123")
    monkeypatch.setattr(settings, "oidc_client_secret", "super-secret-value")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/auth/sso/status")
        body = resp.json()
        assert body["oidc"]["configured"] is True
        assert body["oidc"]["issuer_url"] == "https://idp.example.test"
        assert "super-secret-value" not in resp.text


def test_oidc_configured_requires_all_three_settings():
    assert settings.oidc_configured is False
