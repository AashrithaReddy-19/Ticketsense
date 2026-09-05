"""Section 20: predictive-prevention recommendation APIs."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.platform import AuditLog, Incident, KnowledgeArticle
from app.models.prevention import PreventionRecommendation, RecommendationAction, RecommendationEvidence
from app.models.user import User
from app.services.prevention import generate_recommendations

router = APIRouter(prefix="/api/prevention", tags=["prevention"])


class DismissRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class LinkIncidentRequest(BaseModel):
    incident_id: UUID


async def require(db: AsyncSession, user: User, permission: str = "prevention:manage") -> None:
    if not await user_has_permission(db, user, permission):
        raise HTTPException(403, f"Permission required: {permission}")


def recommendation_json(r: PreventionRecommendation) -> dict:
    return {"id": r.id, "department_id": r.department_id, "category": r.category, "recommendation_type": r.recommendation_type,
            "title": r.title, "description": r.description, "window_days": r.window_days,
            "supporting_ticket_count": r.supporting_ticket_count, "evidence_strength": r.evidence_strength,
            "expected_benefit": r.expected_benefit, "status": r.status, "decision_reason": r.decision_reason,
            "linked_incident_id": r.linked_incident_id, "linked_knowledge_article_id": r.linked_knowledge_article_id,
            "generated_at": r.generated_at, "decided_by": r.decided_by, "decided_at": r.decided_at, "created_at": r.created_at}


async def get_owned(db: AsyncSession, user: User, recommendation_id: UUID) -> PreventionRecommendation:
    rec = await db.scalar(select(PreventionRecommendation).where(
        PreventionRecommendation.id == recommendation_id, PreventionRecommendation.tenant_id == user.tenant_id).with_for_update())
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    return rec


@router.post("/scan")
async def scan_for_recommendations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user)
    created = await generate_recommendations(db, user.tenant_id)
    await db.commit()
    for rec in created:
        await db.refresh(rec)
    return [recommendation_json(r) for r in created]


@router.get("/recommendations")
async def list_recommendations(department_id: UUID | None = None, recommendation_type: str = "", status_filter: str = "",
                                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user)
    query = select(PreventionRecommendation).where(PreventionRecommendation.tenant_id == user.tenant_id)
    if department_id:
        query = query.where(PreventionRecommendation.department_id == department_id)
    if recommendation_type:
        query = query.where(PreventionRecommendation.recommendation_type == recommendation_type)
    if status_filter:
        query = query.where(PreventionRecommendation.status == status_filter)
    rows = (await db.scalars(query.order_by(PreventionRecommendation.generated_at.desc()))).all()
    return [recommendation_json(r) for r in rows]


@router.get("/recommendations/{recommendation_id}")
async def get_recommendation(recommendation_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user)
    rec = await db.scalar(select(PreventionRecommendation).where(PreventionRecommendation.id == recommendation_id, PreventionRecommendation.tenant_id == user.tenant_id))
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    evidence = (await db.scalars(select(RecommendationEvidence).where(RecommendationEvidence.recommendation_id == rec.id))).all()
    actions = (await db.scalars(select(RecommendationAction).where(RecommendationAction.recommendation_id == rec.id).order_by(RecommendationAction.created_at))).all()
    return {**recommendation_json(rec),
            "evidence": [{"evidence_type": e.evidence_type, "reference_id": e.reference_id, "detail": e.detail} for e in evidence],
            "actions": [{"action_type": a.action_type, "actor_id": a.actor_id, "reason": a.reason, "created_at": a.created_at} for a in actions]}


async def _transition(db: AsyncSession, user: User, rec: PreventionRecommendation, new_status: str, action_type: str, reason: str | None = None) -> None:
    rec.status = new_status
    rec.decided_by = user.id
    from datetime import datetime, timezone
    rec.decided_at = datetime.now(timezone.utc)
    if reason:
        rec.decision_reason = reason
    db.add(RecommendationAction(recommendation_id=rec.id, actor_id=user.id, action_type=action_type, reason=reason))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action=f"prevention.{action_type}", resource_type="prevention_recommendation",
                     resource_id=str(rec.id), metadata_json={"status": new_status}))


@router.post("/recommendations/{recommendation_id}/accept")
async def accept_recommendation(recommendation_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user)
    rec = await get_owned(db, user, recommendation_id)
    if rec.status not in ("new", "under_investigation"):
        raise HTTPException(409, "Only a new or under-investigation recommendation can be accepted")
    await _transition(db, user, rec, "accepted", "accept")
    await db.commit()
    await db.refresh(rec)
    return recommendation_json(rec)


@router.post("/recommendations/{recommendation_id}/reject")
async def reject_recommendation(recommendation_id: UUID, payload: DismissRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user)
    rec = await get_owned(db, user, recommendation_id)
    if rec.status not in ("new", "under_investigation"):
        raise HTTPException(409, "Only a new or under-investigation recommendation can be rejected")
    await _transition(db, user, rec, "rejected", "reject", payload.reason)
    await db.commit()
    await db.refresh(rec)
    return recommendation_json(rec)


@router.post("/recommendations/{recommendation_id}/investigate")
async def investigate_recommendation(recommendation_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user)
    rec = await get_owned(db, user, recommendation_id)
    if rec.status != "new":
        raise HTTPException(409, "Only a new recommendation can be marked under investigation")
    await _transition(db, user, rec, "under_investigation", "investigate")
    await db.commit()
    await db.refresh(rec)
    return recommendation_json(rec)


@router.post("/recommendations/{recommendation_id}/dismiss")
async def dismiss_recommendation(recommendation_id: UUID, payload: DismissRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user)
    rec = await get_owned(db, user, recommendation_id)
    if rec.status in ("converted",):
        raise HTTPException(409, "A converted recommendation cannot be dismissed")
    await _transition(db, user, rec, "dismissed", "dismiss", payload.reason)
    await db.commit()
    await db.refresh(rec)
    return recommendation_json(rec)


@router.post("/recommendations/{recommendation_id}/convert-to-knowledge", status_code=201)
async def convert_to_knowledge(recommendation_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user)
    rec = await get_owned(db, user, recommendation_id)
    if rec.status not in ("new", "under_investigation", "accepted"):
        raise HTTPException(409, "This recommendation cannot be converted from its current status")
    if rec.recommendation_type not in ("create_knowledge_article", "update_knowledge_article"):
        raise HTTPException(422, "Only a create/update-knowledge-article recommendation can be converted")
    article = KnowledgeArticle(tenant_id=user.tenant_id, department_id=rec.department_id, title=rec.title[:255],
                               body=f"{rec.description}\n\nExpected benefit: {rec.expected_benefit}", status="pending_review",
                               source_ticket_ids=[], source_signal="predictive_prevention")
    db.add(article)
    await db.flush()
    rec.linked_knowledge_article_id = article.id
    await _transition(db, user, rec, "converted", "convert_to_knowledge")
    db.add(RecommendationAction(recommendation_id=rec.id, actor_id=user.id, action_type="convert_to_knowledge", result_reference_id=article.id))
    await db.commit()
    await db.refresh(rec)
    return {"recommendation": recommendation_json(rec), "knowledge_article_id": article.id}


@router.post("/recommendations/{recommendation_id}/link-incident")
async def link_incident(recommendation_id: UUID, payload: LinkIncidentRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user)
    rec = await get_owned(db, user, recommendation_id)
    incident = await db.scalar(select(Incident).where(Incident.id == payload.incident_id, Incident.tenant_id == user.tenant_id))
    if not incident:
        raise HTTPException(404, "Incident not found")
    rec.linked_incident_id = incident.id
    db.add(RecommendationAction(recommendation_id=rec.id, actor_id=user.id, action_type="link_incident", result_reference_id=incident.id))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="prevention.link_incident", resource_type="prevention_recommendation",
                     resource_id=str(rec.id), metadata_json={"incident_id": str(incident.id)}))
    await db.commit()
    await db.refresh(rec)
    return recommendation_json(rec)
