"""TicketSense V2 external connector API. A connector is only ever "verified"
after a real outbound check succeeds — never on configuration alone — and
only the allowlisted Slack provider currently has a real implementation;
every other provider honestly reports itself as not yet implemented. See
app.services.connectors for the resolution and verification logic."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.platform import AuditLog, Integration
from app.models.user import User
from app.services.connectors.registry import verify_connector
from app.services.feature_flags import require_feature

router = APIRouter(prefix="/api/v2/connectors", tags=["v2-connectors"])

CONFIG_REFERENCE_PREFIXES = ("env:", "secret-manager:", "none:", "file:")


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_flag(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "external_connectors", user, permissions)


def connector_json(row: Integration) -> dict:
    return {
        "id": row.id, "provider": row.provider, "name": row.name, "enabled": row.enabled,
        "config_reference": row.config_reference, "status": row.status,
        "last_verified_at": row.last_verified_at, "last_verified_by": row.last_verified_by,
        "last_error": row.last_error,
    }


@router.get("")
async def list_connectors(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "integration:read")
    await require_flag(db, user)
    rows = (await db.scalars(select(Integration).where(Integration.tenant_id == user.tenant_id).order_by(Integration.provider))).all()
    return {"items": [connector_json(r) for r in rows]}


class ConfigureRequest(BaseModel):
    config_reference: str = Field(min_length=1, max_length=200)

    @field_validator("config_reference")
    @classmethod
    def safe_reference(cls, value: str) -> str:
        if not value.startswith(CONFIG_REFERENCE_PREFIXES):
            raise ValueError("config_reference must start with env:, secret-manager:, none: or file:")
        return value


@router.post("/{connector_id}/configure")
async def configure_connector(connector_id: UUID, payload: ConfigureRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "integration:manage")
    await require_flag(db, user)
    row = await db.scalar(select(Integration).where(Integration.id == connector_id, Integration.tenant_id == user.tenant_id).with_for_update())
    if not row:
        raise HTTPException(404, "Connector not found")
    row.config_reference = payload.config_reference
    row.status = "unverified"
    row.enabled = False
    row.last_error = None
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.connector.configured", resource_type="integration", resource_id=str(row.id), metadata_json={"provider": row.provider}))
    await db.commit(); await db.refresh(row)
    return connector_json(row)


@router.post("/{connector_id}/verify")
async def verify_connector_endpoint(connector_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "integration:manage")
    await require_flag(db, user)
    row = await db.scalar(select(Integration).where(Integration.id == connector_id, Integration.tenant_id == user.tenant_id).with_for_update())
    if not row:
        raise HTTPException(404, "Connector not found")
    result = await verify_connector(row.provider, row.config_reference)
    row.status = "verified" if result.success else ("failed" if row.config_reference else "not_configured")
    row.enabled = result.success
    row.last_error = None if result.success else result.reason
    if result.success:
        row.last_verified_at = datetime.now(timezone.utc)
        row.last_verified_by = user.id
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.connector.verified", resource_type="integration", resource_id=str(row.id), metadata_json={"provider": row.provider, "success": result.success, "reason": result.reason}))
    await db.commit(); await db.refresh(row)
    return connector_json(row)
