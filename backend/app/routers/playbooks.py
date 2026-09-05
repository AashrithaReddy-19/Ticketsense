"""Section 13: smart resolution playbook management and application APIs."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.enterprise import DiagnosticStep
from app.models.platform import AuditLog
from app.models.playbook import Playbook, PlaybookApplication
from app.models.user import User
from app.services.playbooks import apply_playbook, match_playbook, next_version
from app.services.ticket_visibility import get_visible_ticket

router = APIRouter(prefix="/api", tags=["playbooks"])


class PlaybookStep(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    instruction: str = Field(min_length=3, max_length=4000)
    safety_warning: str | None = Field(default=None, max_length=1000)
    evidence_required: bool = False


class PlaybookCreate(BaseModel):
    playbook_key: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=3, max_length=255)
    category: str = Field(min_length=2, max_length=120)
    applicable_error_codes: list[str] = Field(default_factory=list, max_length=50)
    clarification_questions: list[str] = Field(default_factory=list, max_length=20)
    evidence_requirements: list[str] = Field(default_factory=list, max_length=20)
    diagnostic_steps_template: list[PlaybookStep] = Field(default_factory=list, max_length=30)
    approved_actions: list[str] = Field(default_factory=list, max_length=20)
    safety_warnings: list[str] = Field(default_factory=list, max_length=20)
    resolution_template: str | None = Field(default=None, max_length=8000)
    escalation_rules: list[str] = Field(default_factory=list, max_length=20)
    auto_resolution_eligible: bool = False
    reason: str = Field(min_length=3, max_length=1000)


async def require(db: AsyncSession, user: User, permission: str) -> None:
    if not await user_has_permission(db, user, permission):
        raise HTTPException(403, f"Permission required: {permission}")


def playbook_json(playbook: Playbook) -> dict:
    return {"id": playbook.id, "playbook_key": playbook.playbook_key, "title": playbook.title, "category": playbook.category,
            "version": playbook.version, "status": playbook.status, "applicable_error_codes": playbook.applicable_error_codes,
            "clarification_questions": playbook.clarification_questions, "evidence_requirements": playbook.evidence_requirements,
            "diagnostic_steps_template": playbook.diagnostic_steps_template, "approved_actions": playbook.approved_actions,
            "safety_warnings": playbook.safety_warnings, "resolution_template": playbook.resolution_template,
            "escalation_rules": playbook.escalation_rules, "auto_resolution_eligible": playbook.auto_resolution_eligible,
            "superseded_by_id": playbook.superseded_by_id, "reason": playbook.reason, "created_at": playbook.created_at,
            "updated_at": playbook.updated_at}


@router.get("/playbooks")
async def list_playbooks(status_filter: str = "", category: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "playbook:manage")
    query = select(Playbook).where(Playbook.tenant_id == user.tenant_id)
    if status_filter:
        query = query.where(Playbook.status == status_filter)
    if category:
        query = query.where(Playbook.category == category)
    rows = (await db.scalars(query.order_by(Playbook.playbook_key, Playbook.version.desc()))).all()
    return [playbook_json(row) for row in rows]


@router.post("/playbooks", status_code=201)
async def create_playbook(payload: PlaybookCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "playbook:manage")
    version = await next_version(db, user.tenant_id, payload.playbook_key)
    playbook = Playbook(tenant_id=user.tenant_id, playbook_key=payload.playbook_key, title=payload.title, category=payload.category,
                         version=version, status="draft", applicable_error_codes=payload.applicable_error_codes,
                         clarification_questions=payload.clarification_questions, evidence_requirements=payload.evidence_requirements,
                         diagnostic_steps_template=[step.model_dump() for step in payload.diagnostic_steps_template],
                         approved_actions=payload.approved_actions, safety_warnings=payload.safety_warnings,
                         resolution_template=payload.resolution_template, escalation_rules=payload.escalation_rules,
                         auto_resolution_eligible=payload.auto_resolution_eligible, created_by=user.id, reason=payload.reason)
    db.add(playbook)
    await db.flush()
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="playbook.created", resource_type="playbook", resource_id=str(playbook.id),
                     metadata_json={"playbook_key": payload.playbook_key, "version": version}))
    await db.commit()
    await db.refresh(playbook)
    return playbook_json(playbook)


async def get_owned_playbook(db: AsyncSession, user: User, playbook_id: UUID) -> Playbook:
    playbook = await db.scalar(select(Playbook).where(Playbook.id == playbook_id, Playbook.tenant_id == user.tenant_id).with_for_update())
    if not playbook:
        raise HTTPException(404, "Playbook not found")
    return playbook


@router.post("/playbooks/{playbook_id}/version", status_code=201)
async def new_playbook_version(playbook_id: UUID, payload: PlaybookCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Creates a new draft version. Playbooks are immutable once created — this
    is the only way to change one, exactly like DepartmentResolutionPolicy."""
    await require(db, user, "playbook:manage")
    previous = await get_owned_playbook(db, user, playbook_id)
    if payload.playbook_key != previous.playbook_key:
        raise HTTPException(422, "A new version must keep the same playbook_key")
    version = await next_version(db, user.tenant_id, payload.playbook_key)
    playbook = Playbook(tenant_id=user.tenant_id, playbook_key=payload.playbook_key, title=payload.title, category=payload.category,
                         version=version, status="draft", applicable_error_codes=payload.applicable_error_codes,
                         clarification_questions=payload.clarification_questions, evidence_requirements=payload.evidence_requirements,
                         diagnostic_steps_template=[step.model_dump() for step in payload.diagnostic_steps_template],
                         approved_actions=payload.approved_actions, safety_warnings=payload.safety_warnings,
                         resolution_template=payload.resolution_template, escalation_rules=payload.escalation_rules,
                         auto_resolution_eligible=payload.auto_resolution_eligible, created_by=user.id, reason=payload.reason)
    db.add(playbook)
    await db.flush()
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="playbook.new_version", resource_type="playbook", resource_id=str(playbook.id),
                     metadata_json={"playbook_key": payload.playbook_key, "version": version, "previous_id": str(previous.id)}))
    await db.commit()
    await db.refresh(playbook)
    return playbook_json(playbook)


@router.post("/playbooks/{playbook_id}/approve")
async def approve_playbook(playbook_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "playbook:manage")
    playbook = await get_owned_playbook(db, user, playbook_id)
    if playbook.status != "draft":
        raise HTTPException(409, "Only a draft playbook can be approved")
    playbook.status = "approved"
    playbook.approved_by = user.id
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="playbook.approved", resource_type="playbook", resource_id=str(playbook.id), metadata_json={}))
    await db.commit()
    await db.refresh(playbook)
    return playbook_json(playbook)


@router.post("/playbooks/{playbook_id}/activate")
async def activate_playbook(playbook_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "playbook:manage")
    playbook = await get_owned_playbook(db, user, playbook_id)
    if playbook.status != "approved":
        raise HTTPException(409, "Only an approved playbook can be activated")
    previously_active = list((await db.scalars(
        select(Playbook).where(Playbook.tenant_id == user.tenant_id, Playbook.playbook_key == playbook.playbook_key,
                                Playbook.status == "active", Playbook.id != playbook.id)
    )).all())
    for old in previously_active:
        old.status = "superseded"
        old.superseded_by_id = playbook.id
    playbook.status = "active"
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="playbook.activated", resource_type="playbook", resource_id=str(playbook.id),
                     metadata_json={"superseded": [str(p.id) for p in previously_active]}))
    await db.commit()
    await db.refresh(playbook)
    return playbook_json(playbook)


@router.post("/playbooks/{playbook_id}/deactivate")
async def deactivate_playbook(playbook_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "playbook:manage")
    playbook = await get_owned_playbook(db, user, playbook_id)
    if playbook.status != "active":
        raise HTTPException(409, "Only an active playbook can be deactivated")
    playbook.status = "inactive"
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="playbook.deactivated", resource_type="playbook", resource_id=str(playbook.id), metadata_json={}))
    await db.commit()
    await db.refresh(playbook)
    return playbook_json(playbook)


@router.get("/tickets/{ticket_id}/recommended-playbook")
async def recommended_playbook(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "diagnostic:manage")
    ticket = await get_visible_ticket(db, user, ticket_id)
    playbook = await match_playbook(db, ticket)
    if not playbook:
        raise HTTPException(404, "No matching active playbook for this ticket's category")
    return playbook_json(playbook)


@router.post("/tickets/{ticket_id}/playbooks/{playbook_id}/apply", status_code=201)
async def apply_playbook_to_ticket(ticket_id: UUID, playbook_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "diagnostic:manage")
    ticket = await get_visible_ticket(db, user, ticket_id)
    if user.public_role == "engineer" and ticket.assignee_id != user.id:
        raise HTTPException(403, "Only the assigned Engineer can apply a playbook to this ticket")
    playbook = await db.scalar(select(Playbook).where(Playbook.id == playbook_id, Playbook.tenant_id == user.tenant_id, Playbook.status == "active"))
    if not playbook:
        raise HTTPException(404, "Active playbook not found")
    plan = await apply_playbook(db, ticket, playbook, user.id)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="playbook.applied", resource_type="ticket", resource_id=str(ticket.id),
                     metadata_json={"playbook_id": str(playbook.id), "diagnostic_plan_id": str(plan.id)}))
    await db.commit()
    steps = list((await db.scalars(select(DiagnosticStep).where(DiagnosticStep.plan_id == plan.id).order_by(DiagnosticStep.sequence_number))).all())
    return {"diagnostic_plan_id": plan.id, "playbook_id": playbook.id, "step_count": len(steps)}
