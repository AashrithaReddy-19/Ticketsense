"""TicketSense V2 Resolution Passport API.

Every resolution flow already writes a passport transactionally (see
app.services.passport.create_passport, called from resolution_policy.py and
workflow.py). This router only reads and verifies what's already there — it
never creates a passport as a side effect of a GET, and the backfill job is
the one narrow, explicit, audited exception for tickets resolved before this
feature existed.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import is_customer
from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.platform import AuditLog
from app.models.resolution_passport import ResolutionPassport
from app.models.response_draft import ResponseDraft
from app.models.ticket import Ticket
from app.models.user import User
from app.services.passport import create_passport, customer_json, internal_json, recompute_integrity_hash
from app.services.feature_flags import require_feature
from app.services.ticket_visibility import get_visible_ticket

router = APIRouter(prefix="/api/v2/passports", tags=["v2-resolution-passport"])


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_flag_enabled(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "resolution_passport", user, permissions)


async def _current_passport(db: AsyncSession, ticket_id: UUID, tenant_id) -> ResolutionPassport | None:
    return await db.scalar(
        select(ResolutionPassport).where(
            ResolutionPassport.ticket_id == ticket_id, ResolutionPassport.tenant_id == tenant_id,
            ResolutionPassport.is_current.is_(True),
        )
    )


@router.get("/{ticket_id}")
async def get_passport(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_flag_enabled(db, user)
    ticket = await get_visible_ticket(db, user, ticket_id)
    passport = await _current_passport(db, ticket.id, user.tenant_id)
    if not passport:
        raise HTTPException(404, "No resolution passport exists yet for this ticket")
    integrity_valid = recompute_integrity_hash(passport) == passport.integrity_hash
    if is_customer(user.role):
        return await customer_json(db, passport, integrity_valid)
    await require(db, user, "passport:read")
    return internal_json(passport, integrity_valid)


@router.get("/{ticket_id}/history")
async def passport_history(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_flag_enabled(db, user)
    await require(db, user, "passport:read")
    ticket = await get_visible_ticket(db, user, ticket_id)
    rows = (await db.scalars(
        select(ResolutionPassport).where(ResolutionPassport.ticket_id == ticket.id, ResolutionPassport.tenant_id == user.tenant_id)
        .order_by(ResolutionPassport.created_at.asc())
    )).all()
    return {"items": [internal_json(row, recompute_integrity_hash(row) == row.integrity_hash) for row in rows]}


@router.get("/{ticket_id}/verify")
async def verify_passport(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_flag_enabled(db, user)
    await require(db, user, "passport:read")
    ticket = await get_visible_ticket(db, user, ticket_id)
    passport = await _current_passport(db, ticket.id, user.tenant_id)
    if not passport:
        raise HTTPException(404, "No resolution passport exists yet for this ticket")
    recomputed = recompute_integrity_hash(passport)
    return {"passport_id": passport.id, "valid": recomputed == passport.integrity_hash, "stored_hash": passport.integrity_hash, "recomputed_hash": recomputed}


@router.get("/{ticket_id}/export")
async def export_passport(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_flag_enabled(db, user)
    await require(db, user, "passport:export")
    ticket = await get_visible_ticket(db, user, ticket_id)
    passport = await _current_passport(db, ticket.id, user.tenant_id)
    if not passport:
        raise HTTPException(404, "No resolution passport exists yet for this ticket")
    integrity_valid = recompute_integrity_hash(passport) == passport.integrity_hash
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.passport.exported", resource_type="resolution_passport", resource_id=str(passport.id), metadata_json={"ticket_id": str(ticket_id)}))
    await db.commit()
    return internal_json(passport, integrity_valid)


@router.post("/backfill")
async def backfill_passports(limit: int = Query(200, ge=1, le=1000), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Best-effort passport reconstruction for tickets resolved before this
    feature existed. Marked is_backfilled=True so nobody mistakes a
    reconstructed record for one created live at resolution time — a
    backfilled passport can only use whatever TicketDecision/ResponseDraft
    data still exists; it never fabricates gate results that were never
    actually recorded."""
    await require_flag_enabled(db, user)
    await require(db, user, "passport:manage")

    candidates = (await db.scalars(
        select(Ticket).where(
            Ticket.tenant_id == user.tenant_id, Ticket.deleted_at.is_(None),
            Ticket.status.in_(["resolved_by_ai", "resolved_by_engineer", "resolved", "closed"]),
            Ticket.final_response_draft_id.isnot(None),
        ).limit(limit)
    )).all()

    created, skipped = 0, 0
    for ticket in candidates:
        existing = await _current_passport(db, ticket.id, user.tenant_id)
        if existing:
            skipped += 1
            continue
        response_draft = await db.scalar(select(ResponseDraft).where(ResponseDraft.id == ticket.final_response_draft_id))
        if not response_draft:
            skipped += 1
            continue
        from app.models.enterprise import TicketDecision
        decision = await db.scalar(
            select(TicketDecision).where(TicketDecision.ticket_id == ticket.id).order_by(TicketDecision.created_at.desc())
        )
        resolution_type = ticket.resolution_type or ("ai" if decision else "engineer")
        await create_passport(
            db, ticket, response_draft, resolution_type=resolution_type, created_by=user.id,
            decision=decision, is_backfilled=True,
        )
        created += 1

    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.passport.backfilled", resource_type="resolution_passport", resource_id=None, metadata_json={"created": created, "skipped": skipped}))
    await db.commit()
    return {"created": created, "skipped": skipped, "candidates_examined": len(candidates)}
