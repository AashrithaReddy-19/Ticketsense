"""TicketSense V2 knowledge-conflict detection API. A conflict is a review
task, never an automatic edit or deletion of an article — see
app.services.knowledge_conflicts.detector.
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.knowledge_conflict import KnowledgeConflict
from app.models.platform import AuditLog
from app.models.user import User
from app.services.feature_flags import require_feature
from app.services.knowledge_conflicts.detector import run_all_detectors

router = APIRouter(prefix="/api/v2/knowledge-conflicts", tags=["v2-knowledge-conflicts"])


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_flag(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "knowledge_conflict_detection", user, permissions)


def conflict_json(row: KnowledgeConflict) -> dict:
    return {
        "id": row.id, "article_a_id": row.article_a_id, "article_b_id": row.article_b_id,
        "conflict_type": row.conflict_type, "severity": row.severity,
        "evidence_excerpt_a": row.evidence_excerpt_a, "evidence_excerpt_b": row.evidence_excerpt_b,
        "confidence": float(row.confidence) if row.confidence is not None else None, "sample_size": row.sample_size,
        "affected_ticket_ids": row.affected_ticket_ids, "review_state": row.review_state,
        "resolved_by": row.resolved_by, "resolved_at": row.resolved_at, "resolution_note": row.resolution_note,
        "created_at": row.created_at,
    }


@router.post("/scan", status_code=201)
async def scan(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "knowledge_conflict:manage")
    await require_flag(db, user)
    created = await run_all_detectors(db, user.tenant_id)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.knowledge_conflict.scanned", resource_type="knowledge_conflict", resource_id=None, metadata_json={"new_conflicts": len(created)}))
    await db.commit()
    return {"new_conflicts": len(created), "conflicts": [conflict_json(c) for c in created]}


@router.get("")
async def list_conflicts(review_state: str | None = None, severity: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "knowledge_conflict:read")
    await require_flag(db, user)
    query = select(KnowledgeConflict).where(KnowledgeConflict.tenant_id == user.tenant_id)
    if review_state:
        query = query.where(KnowledgeConflict.review_state == review_state)
    if severity:
        query = query.where(KnowledgeConflict.severity == severity)
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = (await db.scalars(query.order_by(KnowledgeConflict.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [conflict_json(r) for r in rows], "page": page, "page_size": page_size, "total": total}


class ReviewUpdate(BaseModel):
    review_state: str = Field(pattern="^(reviewing|resolved|dismissed)$")
    resolution_note: str = Field(min_length=3, max_length=2_000)


@router.patch("/{conflict_id}")
async def update_review(conflict_id: UUID, payload: ReviewUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "knowledge_conflict:manage")
    await require_flag(db, user)
    row = await db.scalar(select(KnowledgeConflict).where(KnowledgeConflict.id == conflict_id, KnowledgeConflict.tenant_id == user.tenant_id).with_for_update())
    if not row:
        raise HTTPException(404, "Knowledge conflict not found")
    before = row.review_state
    row.review_state = payload.review_state
    row.resolution_note = payload.resolution_note
    if payload.review_state in ("resolved", "dismissed"):
        row.resolved_by = user.id
        row.resolved_at = datetime.now(timezone.utc)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.knowledge_conflict.reviewed", resource_type="knowledge_conflict", resource_id=str(row.id), metadata_json={"before": before, "after": payload.review_state, "note": payload.resolution_note}))
    await db.commit(); await db.refresh(row)
    return conflict_json(row)
