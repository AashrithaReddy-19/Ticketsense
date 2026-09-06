"""TicketSense V2 Phase 1 governance control plane."""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.department import Department
from app.models.platform import AuditLog
from app.models.user import User
from app.models.v2_governance import (
    CapabilityBundle, FeatureFlag, FeatureFlagAudit, FeatureFlagOverride,
    ModelDeployment, PromptVersion, ProviderModel, UserCapabilityBundle,
)
from app.services.ai_observability import usage_summary
from app.services.feature_flags import evaluate_flag

router = APIRouter(prefix="/api/v2", tags=["v2-governance"])


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def permission_codes(db: AsyncSession, user: User) -> list[str]:
    from app.routers.auth import _permissions
    return await _permissions(db, user)


class FlagCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,99}$")
    description: str = Field(min_length=5, max_length=2_000)
    owner: str = Field(min_length=2, max_length=120)
    global_default: bool = False
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class FlagPatch(BaseModel):
    description: str | None = Field(default=None, min_length=5, max_length=2_000)
    owner: str | None = Field(default=None, min_length=2, max_length=120)
    global_default: bool | None = None
    kill_switch: bool | None = None
    prerequisites: list[str] | None = Field(default=None, max_length=20)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=1_000)


class OverrideCreate(BaseModel):
    scope_type: str = Field(pattern="^(tenant|department|user|role|capability)$")
    scope_value: str = Field(min_length=1, max_length=160)
    enabled: bool
    rollout_percentage: int = Field(default=100, ge=0, le=100)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=1_000)


class ModelCreate(BaseModel):
    provider_type: str = Field(min_length=2, max_length=60)
    model_identifier: str = Field(min_length=2, max_length=160)
    immutable_version: str = Field(min_length=1, max_length=120)
    task_type: str = Field(min_length=2, max_length=80)
    deployment_environment: str = Field(default="development", max_length=40)
    config_reference: str | None = Field(default=None, max_length=200)
    cost_metadata: dict = Field(default_factory=dict)
    latency_limit_ms: int | None = Field(default=None, ge=1, le=600_000)
    data_residency_policy: str = Field(default="tenant_default", max_length=100)
    approved_scopes: dict = Field(default_factory=dict)
    lifecycle_role: str = Field(default="challenger", pattern="^(challenger|shadow)$")

    @field_validator("config_reference")
    @classmethod
    def safe_reference(cls, value: str | None):
        if value is not None and not value.startswith(("env:", "secret-manager:", "none:")):
            raise ValueError("config_reference must name an environment variable or secrets-manager reference")
        return value


class DeploymentRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2_000)


class PromptCreate(BaseModel):
    task_type: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=120)
    version: str = Field(min_length=1, max_length=60)
    template: str = Field(min_length=10, max_length=50_000)
    structured_output_schema: dict = Field(default_factory=dict)
    activate: bool = False


class BundleCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,99}$")
    name: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=5, max_length=2_000)
    permission_codes: list[str] = Field(min_length=1, max_length=100)
    conflicts_with: list[str] = Field(default_factory=list, max_length=30)


class BundleAssign(BaseModel):
    user_id: UUID
    department_id: UUID | None = None
    reason: str = Field(min_length=3, max_length=1_000)


def flag_json(flag: FeatureFlag) -> dict:
    return {"id": flag.id, "key": flag.key, "description": flag.description, "owner": flag.owner,
        "global_default": flag.global_default, "kill_switch": flag.kill_switch,
        "prerequisites": flag.prerequisites, "starts_at": flag.starts_at, "ends_at": flag.ends_at,
        "created_at": flag.created_at, "updated_at": flag.updated_at}


def flag_snapshot(flag: FeatureFlag) -> dict:
    return {"key": flag.key, "description": flag.description, "owner": flag.owner,
        "global_default": flag.global_default, "kill_switch": flag.kill_switch,
        "prerequisites": flag.prerequisites,
        "starts_at": flag.starts_at.isoformat() if flag.starts_at else None,
        "ends_at": flag.ends_at.isoformat() if flag.ends_at else None}


@router.get("/features")
async def features(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "feature:read")
    total = int(await db.scalar(select(func.count()).select_from(FeatureFlag)) or 0)
    rows = (await db.scalars(select(FeatureFlag).order_by(FeatureFlag.key).offset((page - 1) * page_size).limit(page_size))).all()
    permissions = await permission_codes(db, user)
    items = []
    for row in rows:
        decision = await evaluate_flag(db, row.key, user, permissions)
        item = flag_json(row)
        item["evaluation"] = decision.__dict__
        items.append(item)
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/features/{key}/evaluate")
async def feature_evaluation(key: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    permissions = await permission_codes(db, user)
    decision = await evaluate_flag(db, key, user, permissions)
    if await user_has_permission(db, user, "feature:read"):
        return decision.__dict__
    return {"key": key, "enabled": decision.enabled}


@router.post("/features", status_code=201)
async def create_feature(payload: FlagCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "feature:manage_global")
    if await db.scalar(select(FeatureFlag.id).where(FeatureFlag.key == payload.key)):
        raise HTTPException(409, "Feature key already exists")
    known = set(await db.scalars(select(FeatureFlag.key).where(FeatureFlag.key.in_(payload.prerequisites))))
    if known != set(payload.prerequisites):
        raise HTTPException(422, "Every prerequisite must be an existing feature key")
    flag = FeatureFlag(**payload.model_dump(), created_by=user.id)
    db.add(flag)
    await db.flush()
    db.add(FeatureFlagAudit(tenant_id=user.tenant_id, flag_id=flag.id, actor_id=user.id, action="created", after=flag_snapshot(flag)))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.feature.created", resource_type="feature_flag", resource_id=str(flag.id), metadata_json={"key": flag.key}))
    await db.commit(); await db.refresh(flag)
    return flag_json(flag)


@router.patch("/features/{key}")
async def update_feature(key: str, payload: FlagPatch, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "feature:manage_global")
    flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == key).with_for_update())
    if not flag: raise HTTPException(404, "Feature not found")
    before = flag_snapshot(flag)
    changes = payload.model_dump(exclude={"reason"}, exclude_unset=True)
    for field, value in changes.items(): setattr(flag, field, value)
    if key in (flag.prerequisites or []): raise HTTPException(422, "A feature cannot require itself")
    known = set((await db.scalars(select(FeatureFlag.key).where(FeatureFlag.key.in_(flag.prerequisites or [])))).all())
    if known != set(flag.prerequisites or []): raise HTTPException(422, "Every prerequisite must be an existing feature key")
    after = flag_snapshot(flag)
    db.add(FeatureFlagAudit(tenant_id=user.tenant_id, flag_id=flag.id, actor_id=user.id, action="kill_switch" if payload.kill_switch is not None else "updated", before=before, after=after, reason=payload.reason))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.feature.updated", resource_type="feature_flag", resource_id=str(flag.id), metadata_json={"key": key, "kill_switch": flag.kill_switch, "reason": payload.reason}))
    await db.commit(); await db.refresh(flag)
    return flag_json(flag)


async def validate_scope(db: AsyncSession, user: User, scope_type: str, scope_value: str) -> None:
    if scope_type == "tenant" and scope_value != str(user.tenant_id): raise HTTPException(422, "Tenant override must target the current tenant")
    if scope_type in {"department", "user"}:
        try: target_id = UUID(scope_value)
        except ValueError: raise HTTPException(422, f"{scope_type.title()} scope must be a UUID")
        model = Department if scope_type == "department" else User
        if not await db.scalar(select(model.id).where(model.id == target_id, model.tenant_id == user.tenant_id)):
            raise HTTPException(422, f"{scope_type.title()} is outside this tenant")
    if scope_type == "role" and not await db.scalar(text("SELECT id FROM roles WHERE name=:name"), {"name": scope_value}): raise HTTPException(422, "Unknown role")
    if scope_type == "capability" and not await db.scalar(text("SELECT id FROM permissions WHERE code=:code"), {"code": scope_value}): raise HTTPException(422, "Unknown capability")


@router.post("/features/{key}/overrides", status_code=201)
async def set_override(key: str, payload: OverrideCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "feature:manage")
    flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
    if not flag: raise HTTPException(404, "Feature not found")
    await validate_scope(db, user, payload.scope_type, payload.scope_value)
    override = await db.scalar(select(FeatureFlagOverride).where(FeatureFlagOverride.flag_id == flag.id, FeatureFlagOverride.tenant_id == user.tenant_id, FeatureFlagOverride.scope_type == payload.scope_type, FeatureFlagOverride.scope_value == payload.scope_value).with_for_update())
    before = {}
    if override:
        before = {"enabled": override.enabled, "rollout_percentage": override.rollout_percentage, "reason": override.reason}
        for field, value in payload.model_dump().items(): setattr(override, field, value)
        override.updated_by = user.id
        action = "override_updated"
    else:
        override = FeatureFlagOverride(flag_id=flag.id, tenant_id=user.tenant_id, updated_by=user.id, **payload.model_dump())
        db.add(override); await db.flush(); action = "override_created"
    after = {"scope_type": override.scope_type, "scope_value": override.scope_value, "enabled": override.enabled, "rollout_percentage": override.rollout_percentage, "reason": override.reason}
    db.add(FeatureFlagAudit(tenant_id=user.tenant_id, flag_id=flag.id, override_id=override.id, actor_id=user.id, action=action, before=before, after=after, reason=payload.reason))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action=f"v2.feature.{action}", resource_type="feature_flag_override", resource_id=str(override.id), metadata_json={"key": key, **after}))
    await db.commit(); await db.refresh(override)
    return {"id": override.id, **after}


@router.delete("/features/{key}/overrides/{override_id}", status_code=204)
async def remove_override(key: str, override_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "feature:manage")
    row = await db.execute(select(FeatureFlagOverride, FeatureFlag).join(FeatureFlag, FeatureFlag.id == FeatureFlagOverride.flag_id).where(
        FeatureFlagOverride.id == override_id,
        FeatureFlagOverride.tenant_id == user.tenant_id,
        FeatureFlag.key == key,
    ))
    result = row.first()
    if not result: raise HTTPException(404, "Feature override not found")
    override, flag = result
    before = {"scope_type": override.scope_type, "scope_value": override.scope_value, "enabled": override.enabled,
              "rollout_percentage": override.rollout_percentage, "reason": override.reason}
    await db.delete(override)
    db.add(FeatureFlagAudit(tenant_id=user.tenant_id, flag_id=flag.id, actor_id=user.id,
                            action="override_deleted", before=before, reason="Override removed"))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.feature.override_deleted",
                    resource_type="feature_flag_override", resource_id=str(override_id),
                    metadata_json={"key": key, **before}))
    await db.commit()


def model_json(row: ProviderModel) -> dict:
    return {"id": row.id, "provider_type": row.provider_type, "model_identifier": row.model_identifier,
        "immutable_version": row.immutable_version, "task_type": row.task_type,
        "deployment_environment": row.deployment_environment, "config_reference": row.config_reference,
        "enabled": row.enabled, "cost_metadata": row.cost_metadata, "latency_limit_ms": row.latency_limit_ms,
        "data_residency_policy": row.data_residency_policy, "approved_scopes": row.approved_scopes,
        "evaluation_status": row.evaluation_status, "lifecycle_role": row.lifecycle_role,
        "rollback_target_id": row.rollback_target_id, "approved_at": row.approved_at, "deployed_at": row.deployed_at}


@router.get("/models")
async def models(task_type: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "model:read")
    query = select(ProviderModel).where(ProviderModel.tenant_id == user.tenant_id)
    if task_type: query = query.where(ProviderModel.task_type == task_type)
    rows = (await db.scalars(query.order_by(ProviderModel.task_type, ProviderModel.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [model_json(row) for row in rows], "page": page, "page_size": page_size}


@router.post("/models", status_code=201)
async def create_model(payload: ModelCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "model:manage")
    row = ProviderModel(tenant_id=user.tenant_id, created_by=user.id, evaluation_status="not_evaluated", enabled=False, **payload.model_dump())
    db.add(row)
    try: await db.flush()
    except Exception:
        await db.rollback(); raise HTTPException(409, "This immutable provider/model version is already registered")
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.model.registered", resource_type="provider_model", resource_id=str(row.id), metadata_json={"task_type": row.task_type, "role": row.lifecycle_role}))
    await db.commit(); await db.refresh(row)
    return model_json(row)


@router.post("/models/{model_id}/promote")
async def promote_model(model_id: UUID, payload: DeploymentRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "model:manage")
    flags = await permission_codes(db, user)
    if not (await evaluate_flag(db, "challenger_models", user, flags)).enabled:
        raise HTTPException(409, "Champion/challenger deployment is disabled by feature policy")
    target = await db.scalar(select(ProviderModel).where(ProviderModel.id == model_id, ProviderModel.tenant_id == user.tenant_id).with_for_update())
    if not target: raise HTTPException(404, "Model not found")
    if target.evaluation_status != "approved": raise HTTPException(409, "Only an approved evaluation candidate can be promoted")
    current = await db.scalar(select(ProviderModel).where(ProviderModel.tenant_id == user.tenant_id, ProviderModel.task_type == target.task_type, ProviderModel.deployment_environment == target.deployment_environment, ProviderModel.lifecycle_role == "champion", ProviderModel.enabled.is_(True)).with_for_update())
    if current and current.id == target.id: return model_json(target)
    if current: current.lifecycle_role = "retired"; current.enabled = False
    target.rollback_target_id = current.id if current else target.rollback_target_id
    target.lifecycle_role = "champion"; target.enabled = True; target.deployed_by = user.id; target.deployed_at = datetime.now(timezone.utc)
    db.add(ModelDeployment(tenant_id=user.tenant_id, task_type=target.task_type, from_model_id=current.id if current else None, to_model_id=target.id, action="promote", actor_id=user.id, reason=payload.reason, evaluation_snapshot={"evaluation_status": target.evaluation_status}))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.model.promoted", resource_type="provider_model", resource_id=str(target.id), metadata_json={"previous": str(current.id) if current else None, "reason": payload.reason}))
    await db.commit(); await db.refresh(target)
    return model_json(target)


@router.post("/models/{model_id}/rollback")
async def rollback_model(model_id: UUID, payload: DeploymentRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "model:manage")
    current = await db.scalar(select(ProviderModel).where(ProviderModel.id == model_id, ProviderModel.tenant_id == user.tenant_id, ProviderModel.lifecycle_role == "champion", ProviderModel.enabled.is_(True)).with_for_update())
    if not current or not current.rollback_target_id: raise HTTPException(409, "An active champion with a rollback target is required")
    target = await db.scalar(select(ProviderModel).where(ProviderModel.id == current.rollback_target_id, ProviderModel.tenant_id == user.tenant_id).with_for_update())
    if not target: raise HTTPException(409, "Rollback target is unavailable")
    current.lifecycle_role = "retired"; current.enabled = False
    target.lifecycle_role = "champion"; target.enabled = True; target.deployed_by = user.id; target.deployed_at = datetime.now(timezone.utc)
    db.add(ModelDeployment(tenant_id=user.tenant_id, task_type=current.task_type, from_model_id=current.id, to_model_id=target.id, action="rollback", actor_id=user.id, reason=payload.reason, evaluation_snapshot={"rollback": True}))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.model.rolled_back", resource_type="provider_model", resource_id=str(current.id), metadata_json={"target": str(target.id), "reason": payload.reason}))
    await db.commit(); await db.refresh(target)
    return model_json(target)


@router.post("/prompts", status_code=201)
async def create_prompt(payload: PromptCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "prompt:manage")
    digest = sha256(payload.template.encode("utf-8")).hexdigest()
    if payload.activate:
        active = (await db.scalars(select(PromptVersion).where(PromptVersion.tenant_id == user.tenant_id, PromptVersion.task_type == payload.task_type, PromptVersion.name == payload.name, PromptVersion.is_active.is_(True)).with_for_update())).all()
        for row in active: row.is_active = False
    prompt = PromptVersion(tenant_id=user.tenant_id, task_type=payload.task_type, name=payload.name, version=payload.version, template=payload.template, content_hash=digest, structured_output_schema=payload.structured_output_schema, is_active=payload.activate, created_by=user.id, approved_by=user.id if payload.activate else None)
    db.add(prompt)
    try: await db.flush()
    except Exception:
        await db.rollback(); raise HTTPException(409, "This immutable prompt version is already registered")
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.prompt.created", resource_type="prompt_version", resource_id=str(prompt.id), metadata_json={"task_type": prompt.task_type, "version": prompt.version, "content_hash": digest, "active": prompt.is_active}))
    await db.commit(); await db.refresh(prompt)
    return {"id": prompt.id, "task_type": prompt.task_type, "name": prompt.name, "version": prompt.version, "content_hash": prompt.content_hash, "is_active": prompt.is_active}


@router.get("/observability/ai-usage")
async def ai_usage(window_days: int = Query(30, ge=1, le=365), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "observability:read")
    return await usage_summary(db, user.tenant_id, window_days)


@router.get("/capability-bundles")
async def bundles(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "capability_bundle:manage")
    rows = (await db.scalars(select(CapabilityBundle).where(CapabilityBundle.tenant_id == user.tenant_id).order_by(CapabilityBundle.name).offset((page - 1) * page_size).limit(page_size))).all()
    items=[]
    for row in rows:
        codes=list(await db.scalars(text("SELECT p.code FROM permissions p JOIN capability_bundle_permissions cbp ON cbp.permission_id=p.id WHERE cbp.bundle_id=:id ORDER BY p.code"),{"id":row.id}))
        items.append({"id":row.id,"key":row.key,"name":row.name,"description":row.description,"permission_codes":codes,"conflicts_with":row.conflicts_with,"is_active":row.is_active})
    return {"items":items,"page":page,"page_size":page_size}


@router.post("/capability-bundles", status_code=201)
async def create_bundle(payload: BundleCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "capability_bundle:manage")
    known=set(await db.scalars(text("SELECT code FROM permissions WHERE code=ANY(:codes)"),{"codes":payload.permission_codes}))
    if known != set(payload.permission_codes): raise HTTPException(422,"One or more permission codes are unknown")
    bundle=CapabilityBundle(tenant_id=user.tenant_id,key=payload.key,name=payload.name,description=payload.description,conflicts_with=payload.conflicts_with,created_by=user.id)
    db.add(bundle);await db.flush()
    await db.execute(text("INSERT INTO capability_bundle_permissions(bundle_id,permission_id) SELECT :bundle,id FROM permissions WHERE code=ANY(:codes)"),{"bundle":bundle.id,"codes":payload.permission_codes})
    db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="v2.capability_bundle.created",resource_type="capability_bundle",resource_id=str(bundle.id),metadata_json={"key":bundle.key,"permission_codes":sorted(known)}))
    await db.commit();await db.refresh(bundle)
    return {"id":bundle.id,"key":bundle.key,"permission_codes":sorted(known)}


@router.post("/capability-bundles/{bundle_id}/assign")
async def assign_bundle(bundle_id:UUID,payload:BundleAssign,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    await require(db,user,"capability_bundle:manage")
    bundle=await db.scalar(select(CapabilityBundle).where(CapabilityBundle.id==bundle_id,CapabilityBundle.tenant_id==user.tenant_id,CapabilityBundle.is_active.is_(True)))
    target=await db.scalar(select(User).where(User.id==payload.user_id,User.tenant_id==user.tenant_id))
    if not bundle or not target: raise HTTPException(404,"Bundle or target user not found")
    if payload.department_id and not await db.scalar(select(Department.id).where(Department.id==payload.department_id,Department.tenant_id==user.tenant_id)):
        raise HTTPException(422,"Department is outside this tenant")
    assigned=list((await db.scalars(select(CapabilityBundle).join(UserCapabilityBundle,UserCapabilityBundle.bundle_id==CapabilityBundle.id).where(UserCapabilityBundle.user_id==target.id,UserCapabilityBundle.tenant_id==user.tenant_id))).all())
    assigned_keys={item.key for item in assigned};conflicts=set(bundle.conflicts_with or [])
    reverse_conflict={item.key for item in assigned if bundle.key in (item.conflicts_with or [])}
    if assigned_keys & conflicts or reverse_conflict: raise HTTPException(409,"Separation-of-duties conflict prevents this assignment")
    exists=await db.scalar(select(UserCapabilityBundle).where(UserCapabilityBundle.user_id==target.id,UserCapabilityBundle.bundle_id==bundle.id,UserCapabilityBundle.tenant_id==user.tenant_id))
    if not exists: db.add(UserCapabilityBundle(user_id=target.id,bundle_id=bundle.id,tenant_id=user.tenant_id,department_id=payload.department_id,assigned_by=user.id))
    db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="v2.capability_bundle.assigned",resource_type="user",resource_id=str(target.id),metadata_json={"bundle":bundle.key,"reason":payload.reason}))
    await db.commit()
    return {"user_id":target.id,"bundle_id":bundle.id,"assigned":True}
