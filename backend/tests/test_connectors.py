"""Coverage for the V2 Phase 12 external connector (Slack incoming webhook).

Verification must perform a real, allowlisted outbound HTTPS call — never a
fabricated success — and must honestly report itself unconfigured when no
credential is actually present, exactly as it is in this dev/test
environment (no real Slack webhook URL is ever committed to this repo).
"""
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import async_session_maker
from app.main import app
from app.models.platform import Integration
from app.services.connectors.registry import verify_connector
from app.services.connectors.resolve import resolve_config_reference
from app.services.connectors.slack_webhook import ALLOWLISTED_HOST_PREFIX, send_slack_webhook_message, verify as verify_slack
from sqlalchemy import select

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _client_factory(handler):
    def factory(*args, **kwargs):
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))
    return factory


def test_resolve_env_reference_reads_the_real_environment_variable(monkeypatch):
    monkeypatch.setenv("TS_TEST_SLACK_WEBHOOK", "https://hooks.slack.com/services/T000/B000/xxx")
    resolved = resolve_config_reference("env:TS_TEST_SLACK_WEBHOOK")
    assert resolved.value == "https://hooks.slack.com/services/T000/B000/xxx"
    assert resolved.reason is None


def test_resolve_env_reference_missing_variable_is_honest_not_a_crash(monkeypatch):
    monkeypatch.delenv("TS_TEST_SLACK_WEBHOOK_MISSING", raising=False)
    resolved = resolve_config_reference("env:TS_TEST_SLACK_WEBHOOK_MISSING")
    assert resolved.value is None
    assert "not set" in resolved.reason


def test_resolve_none_reference_is_intentionally_disabled_not_an_error():
    resolved = resolve_config_reference("none:disabled")
    assert resolved.value is None
    assert "intentionally" in resolved.reason


def test_resolve_secret_manager_reference_honestly_not_implemented():
    resolved = resolve_config_reference("secret-manager:ticketsense/slack")
    assert resolved.value is None
    assert "not implemented" in resolved.reason


def test_resolve_missing_reference_is_honest_not_configured():
    resolved = resolve_config_reference(None)
    assert resolved.value is None
    assert "No config_reference" in resolved.reason


@pytest.mark.asyncio
async def test_send_slack_webhook_message_rejects_non_allowlisted_host():
    with pytest.raises(ValueError, match="allowlisted"):
        await send_slack_webhook_message("https://evil.example.test/steal", "hi")


@pytest.mark.asyncio
async def test_send_slack_webhook_message_success_with_mocked_transport(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    success, reason = await send_slack_webhook_message(f"{ALLOWLISTED_HOST_PREFIX}T000/B000/xxx", "hello channel")
    assert success is True and reason == "ok"
    assert captured["url"] == f"{ALLOWLISTED_HOST_PREFIX}T000/B000/xxx"
    assert b"hello channel" in captured["body"]


@pytest.mark.asyncio
async def test_send_slack_webhook_message_handles_http_error_honestly(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(lambda req: httpx.Response(404, text="invalid_token")))
    success, reason = await send_slack_webhook_message(f"{ALLOWLISTED_HOST_PREFIX}T000/B000/xxx", "hi")
    assert success is False
    assert "404" in reason and "invalid_token" in reason


@pytest.mark.asyncio
async def test_send_slack_webhook_message_handles_network_error_honestly(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    success, reason = await send_slack_webhook_message(f"{ALLOWLISTED_HOST_PREFIX}T000/B000/xxx", "hi")
    assert success is False and "Network error" in reason


@pytest.mark.asyncio
async def test_verify_slack_without_credential_is_honestly_unconfigured():
    result = await verify_slack(None)
    assert result.success is False
    assert "No config_reference" in result.reason


@pytest.mark.asyncio
async def test_verify_slack_with_mocked_success_marks_verified(monkeypatch):
    monkeypatch.setenv("TS_TEST_SLACK_WEBHOOK_2", f"{ALLOWLISTED_HOST_PREFIX}T111/B111/yyy")
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(lambda req: httpx.Response(200, text="ok")))
    result = await verify_slack("env:TS_TEST_SLACK_WEBHOOK_2")
    assert result.success is True


@pytest.mark.asyncio
async def test_verify_connector_registry_falls_back_honestly_for_unimplemented_providers():
    result = await verify_connector("microsoft_teams", "env:ANYTHING")
    assert result.success is False
    assert "not implemented" in result.reason


async def _token(client, email, password="Demo@123") -> str:
    resp = await client.post("/api/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_connector_endpoints_are_feature_flag_gated_then_honestly_report_state():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {await _token(client, 'sysadmin@demo.com')}"}
        me = await client.get("/api/auth/me", headers=headers)
        tenant_id = me.json()["tenant_id"]

        gated = await client.get("/api/v2/connectors", headers=headers)
        assert gated.status_code == 404

        override = await client.post(
            "/api/v2/features/external_connectors/overrides", headers=headers,
            json={"scope_type": "tenant", "scope_value": tenant_id, "enabled": True, "rollout_percentage": 100, "reason": "Connector test"},
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]
        try:
            listing = await client.get("/api/v2/connectors", headers=headers)
            assert listing.status_code == 200
            items = listing.json()["items"]
            slack_row = next(i for i in items if i["provider"] == "slack")
            assert slack_row["status"] == "not_configured"
            assert slack_row["enabled"] is False

            configured = await client.post(f"/api/v2/connectors/{slack_row['id']}/configure", headers=headers, json={"config_reference": "env:TS_TEST_MISSING_SLACK_URL"})
            assert configured.status_code == 200, configured.text
            assert configured.json()["status"] == "unverified"

            invalid = await client.post(f"/api/v2/connectors/{slack_row['id']}/configure", headers=headers, json={"config_reference": "plaintext-secret-not-allowed"})
            assert invalid.status_code == 422

            # No real webhook URL is configured anywhere in this repo — verification must
            # honestly fail rather than report success.
            verified = await client.post(f"/api/v2/connectors/{slack_row['id']}/verify", headers=headers)
            assert verified.status_code == 200, verified.text
            body = verified.json()
            assert body["status"] == "failed"
            assert body["enabled"] is False
            assert body["last_error"] and "not set" in body["last_error"]
        finally:
            await client.delete(f"/api/v2/features/external_connectors/overrides/{override_id}", headers=headers)
            async with async_session_maker() as db:
                row = await db.scalar(select(Integration).where(Integration.tenant_id == tenant_id, Integration.provider == "slack"))
                if row:
                    row.config_reference = None; row.status = "not_configured"; row.enabled = False
                    row.last_error = None; row.last_verified_at = None; row.last_verified_by = None
                    await db.commit()
