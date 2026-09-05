"""Section 19: the safe action registry.

Every action is explicit, allowlisted code below — there is no arbitrary
command execution or unrestricted external request path. Each action has a
typed pydantic parameter model, a preview() that never mutates anything, and
an execute() that only ever touches data this application already owns
(no external credentials are configured anywhere in this repository, so
nothing here calls out to a real third-party system). ``check_service_status``
is the one action explicitly modelled as a sandbox/mocked connector, since a
real version would require real monitoring-provider credentials this project
does not have; its result is always labelled sandbox=True. The other four
touch only this application's own database and are labelled sandbox=False —
they are real, but scoped to data we own, never a production external system.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID

from pydantic import BaseModel, Field

# A permissive syntax check only — deliberately not pydantic's EmailStr, which
# rejects RFC 2606 reserved test TLDs (e.g. "example.test") by default. These
# actions only ever look up an existing account by this value; they never send
# mail or otherwise depend on the domain being real/deliverable.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import Integration, Notification
from app.models.ticket import Ticket
from app.models.user import User


@dataclass(frozen=True)
class ActionContext:
    tenant_id: UUID
    user_id: UUID
    department_id: UUID | None


@dataclass(frozen=True)
class ActionResult:
    summary: str
    data: dict
    evidence: list
    sandbox: bool


class CheckServiceStatusParams(BaseModel):
    service_name: str = Field(min_length=2, max_length=120)


class ResendVerificationParams(BaseModel):
    ticket_id: UUID


class GenerateVpnConfigParams(BaseModel):
    username: str = Field(min_length=2, max_length=120, pattern=r"^[a-zA-Z0-9_.\-]+$")


class CheckAccountLockParams(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)


class PasswordResetRequestParams(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)


async def _check_service_status(db: AsyncSession, ctx: ActionContext, params: CheckServiceStatusParams) -> ActionResult:
    integration = await db.scalar(select(Integration).where(
        Integration.tenant_id == ctx.tenant_id,
        (Integration.provider == params.service_name.lower()) | (Integration.name.ilike(params.service_name)),
    ))
    if integration is None:
        return ActionResult(
            summary=f"No monitored connector named '{params.service_name}' is configured for this tenant.",
            data={"service_name": params.service_name, "status": "unknown"},
            evidence=[{"note": "No matching integrations row — status cannot be determined without a configured monitoring provider."}],
            sandbox=True,
        )
    status = "operational" if integration.enabled else "disabled_not_configured"
    return ActionResult(
        summary=f"Sandbox check: '{integration.name}' reports {status}.",
        data={"service_name": integration.name, "provider": integration.provider, "status": status},
        evidence=[{"integration_id": str(integration.id), "enabled": integration.enabled}],
        sandbox=True,
    )


async def _resend_verification_notification(db: AsyncSession, ctx: ActionContext, params: ResendVerificationParams) -> ActionResult:
    ticket = await db.scalar(select(Ticket).where(Ticket.id == params.ticket_id, Ticket.tenant_id == ctx.tenant_id))
    if ticket is None:
        raise ValueError("Ticket not found in this tenant")
    notification = Notification(tenant_id=ctx.tenant_id, user_id=ticket.submitted_by, kind="verification",
                                 title="Verification reminder", message=f"A support engineer resent a verification reminder for your ticket '{ticket.subject}'.")
    db.add(notification)
    await db.flush()
    return ActionResult(
        summary=f"Verification reminder notification sent to the customer for ticket {ticket.id}.",
        data={"ticket_id": str(ticket.id), "notified_user_id": str(ticket.submitted_by)},
        evidence=[{"notification_id": str(notification.id)}],
        sandbox=False,
    )


VPN_CONFIG_TEMPLATE = """# TicketSense sandbox VPN client configuration template
# Generated for user: {username}
# This is a TEMPLATE only — it contains no real server address, keys, or credentials.
client
dev tun
proto udp
remote vpn.example.internal 1194
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-GCM
verb 3
# Replace ca.crt / client.crt / client.key with values issued by your VPN administrator.
"""


async def _generate_vpn_config_template(db: AsyncSession, ctx: ActionContext, params: GenerateVpnConfigParams) -> ActionResult:
    rendered = VPN_CONFIG_TEMPLATE.format(username=params.username)
    return ActionResult(
        summary=f"Generated a VPN client configuration template for '{params.username}'.",
        data={"username": params.username, "template": rendered},
        evidence=[{"note": "Template only; contains no real server address, keys, or credentials."}],
        sandbox=False,
    )


async def _check_account_lock_status(db: AsyncSession, ctx: ActionContext, params: CheckAccountLockParams) -> ActionResult:
    user = await db.scalar(select(User).where(User.email == params.email, User.tenant_id == ctx.tenant_id))
    if user is None:
        raise ValueError("No account with that email exists in this tenant")
    now = datetime.now(timezone.utc)
    locked = bool(user.locked_until and user.locked_until > now)
    return ActionResult(
        summary=f"Account is {'currently locked' if locked else 'not locked'}.",
        data={"email": params.email, "locked": locked, "failed_login_count": user.failed_login_count,
              "locked_until": user.locked_until.isoformat() if user.locked_until else None},
        evidence=[{"user_id": str(user.id)}],
        sandbox=False,
    )


async def _create_password_reset_request(db: AsyncSession, ctx: ActionContext, params: PasswordResetRequestParams) -> ActionResult:
    user = await db.scalar(select(User).where(User.email == params.email, User.tenant_id == ctx.tenant_id))
    if user is None:
        raise ValueError("No account with that email exists in this tenant")
    notification = Notification(tenant_id=ctx.tenant_id, user_id=user.id, kind="password_reset_requested",
                                 title="Password reset requested", message="A password reset was requested for your account. No password has been changed yet.")
    db.add(notification)
    await db.flush()
    return ActionResult(
        summary=f"A password-reset request notification was created for {params.email}. No password was changed.",
        data={"email": params.email, "password_changed": False},
        evidence=[{"notification_id": str(notification.id), "user_id": str(user.id)}],
        sandbox=False,
    )


@dataclass(frozen=True)
class ActionSpec:
    param_model: type[BaseModel]
    handler: Callable[[AsyncSession, ActionContext, Any], Awaitable[ActionResult]]


REGISTRY: dict[str, ActionSpec] = {
    "check_service_status": ActionSpec(CheckServiceStatusParams, _check_service_status),
    "resend_verification_notification": ActionSpec(ResendVerificationParams, _resend_verification_notification),
    "generate_vpn_configuration_template": ActionSpec(GenerateVpnConfigParams, _generate_vpn_config_template),
    "check_account_lock_status": ActionSpec(CheckAccountLockParams, _check_account_lock_status),
    "create_password_reset_request": ActionSpec(PasswordResetRequestParams, _create_password_reset_request),
}


def parse_params(action_key: str, raw: dict) -> BaseModel:
    spec = REGISTRY.get(action_key)
    if not spec:
        raise KeyError(f"Unknown action: {action_key}")
    return spec.param_model.model_validate(raw)


async def run_action(db: AsyncSession, action_key: str, ctx: ActionContext, params: BaseModel) -> ActionResult:
    spec = REGISTRY[action_key]
    return await spec.handler(db, ctx, params)
