"""A real, production-shaped Slack incoming-webhook connector.

Verification performs an actual outbound HTTPS POST — never a fabricated
success — but only to a fixed, allowlisted host (Slack's own webhook
domain), never to a URL supplied by ticket/user content, so a misconfigured
or malicious config_reference can never be turned into an arbitrary
outbound request (SSRF). If no real webhook URL is configured in this
deployment, verification honestly reports that instead of pretending to
have sent anything."""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.services.connectors.resolve import resolve_config_reference

ALLOWLISTED_HOST_PREFIX = "https://hooks.slack.com/services/"
TIMEOUT_SECONDS = 5.0


@dataclass
class ConnectorVerifyResult:
    success: bool
    reason: str


async def send_slack_webhook_message(webhook_url: str, text: str) -> tuple[bool, str]:
    if not webhook_url.startswith(ALLOWLISTED_HOST_PREFIX):
        raise ValueError(f"Refusing to call a non-allowlisted host; Slack webhook URLs must start with {ALLOWLISTED_HOST_PREFIX}")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(webhook_url, json={"text": text})
    except httpx.RequestError as exc:
        return False, f"Network error calling Slack: {exc}"
    if 200 <= response.status_code < 300:
        return True, "ok"
    return False, f"Slack responded with HTTP {response.status_code}: {response.text[:200]}"


async def verify(config_reference: str | None) -> ConnectorVerifyResult:
    resolved = resolve_config_reference(config_reference)
    if resolved.value is None:
        return ConnectorVerifyResult(False, resolved.reason or "Connector is not configured")
    try:
        success, reason = await send_slack_webhook_message(resolved.value, "TicketSense connector verification: this channel is now connected.")
    except ValueError as exc:
        return ConnectorVerifyResult(False, str(exc))
    return ConnectorVerifyResult(success, reason)
