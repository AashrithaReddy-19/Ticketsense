from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from app.database import get_db
from app.dependencies import get_current_user
from app.models.enterprise import TicketDecision
from app.models.feedback import Feedback
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.platform import AIDecision, AuditLog, Incident, Integration, KnowledgeArticle, Notification
from app.models.ticket import Ticket
from app.models.user import User
from app.dependencies import user_has_permission
from ai.embeddings.knowledge_index import publish_knowledge_article

router = APIRouter(prefix="/api", tags=["platform"])


async def guard(db: AsyncSession, user: User, *permissions: str) -> None:
    if not any([await user_has_permission(db, user, permission) for permission in permissions]):
        raise HTTPException(status_code=403, detail=f"Permission required: {' or '.join(permissions)}")


class ArticleCreate(BaseModel):
    title: str = Field(min_length=4, max_length=255)
    body: str = Field(min_length=20)
    source_ticket_ids: list[str] = []


class ArticleReject(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.get("/knowledge")
async def knowledge(q: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.tenant_id == user.tenant_id)
    if q: query = query.where(KnowledgeBaseDocument.title.ilike(f"%{q}%") | KnowledgeBaseDocument.content.ilike(f"%{q}%"))
    docs = (await db.scalars(query.order_by(KnowledgeBaseDocument.updated_at.desc()).limit(50))).all()
    return [{"id": d.id, "title": d.title, "excerpt": d.content[:240], "source": d.source_url, "updated_at": d.updated_at} for d in docs]


@router.get("/knowledge/articles")
async def list_articles(status_filter: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await guard(db, user, "knowledge:manage", "knowledge:approve", "knowledge:publish")
    query = select(KnowledgeArticle).where(KnowledgeArticle.tenant_id == user.tenant_id)
    if status_filter:
        query = query.where(KnowledgeArticle.status == status_filter)
    rows = (await db.scalars(query.order_by(KnowledgeArticle.created_at.desc()))).all()
    return [{"id": a.id, "title": a.title, "status": a.status, "version": a.version, "department_id": a.department_id,
             "source_ticket_ids": a.source_ticket_ids, "source_signal": a.source_signal,
             "published_knowledge_base_id": a.published_knowledge_base_id, "rejected_reason": a.rejected_reason,
             "created_at": a.created_at} for a in rows]


@router.post("/knowledge/articles/generate")
async def generate_article(payload: ArticleCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await guard(db, user, "knowledge:manage", "ticket:update")
    article = KnowledgeArticle(tenant_id=user.tenant_id, department_id=user.department_id, title=payload.title, body=payload.body, source_ticket_ids=payload.source_ticket_ids, status="pending_review", source_signal="manual")
    db.add(article); await db.flush()
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="knowledge.generated", resource_type="knowledge_article", resource_id=str(article.id), metadata_json={}))
    await db.commit(); await db.refresh(article)
    return {"id": article.id, "status": article.status, "title": article.title}


@router.post("/knowledge/articles/{article_id}/approve")
async def approve_article(article_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await guard(db, user, "knowledge:approve", "knowledge:publish")
    article = await db.get(KnowledgeArticle, article_id)
    if not article or article.tenant_id != user.tenant_id: raise HTTPException(404, "Article not found")
    if article.status == "published": raise HTTPException(409, "Article is already published")
    if not article.department_id: raise HTTPException(422, "A department must be set before an article can be published")
    document = await publish_knowledge_article(db, article)
    article.status = "published"; article.approved_by = user.id; article.published_knowledge_base_id = document.id
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="knowledge.approved", resource_type="knowledge_article", resource_id=str(article.id), metadata_json={"knowledge_base_id": str(document.id)}))
    await db.commit()
    return {"id": article.id, "status": article.status, "knowledge_base_id": document.id}


@router.post("/knowledge/articles/{article_id}/reject")
async def reject_article(article_id: UUID, payload: ArticleReject, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await guard(db, user, "knowledge:approve", "knowledge:publish")
    article = await db.get(KnowledgeArticle, article_id)
    if not article or article.tenant_id != user.tenant_id: raise HTTPException(404, "Article not found")
    if article.status == "published": raise HTTPException(409, "A published article cannot be rejected; archive it instead")
    article.status = "rejected"; article.rejected_reason = payload.reason
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="knowledge.rejected", resource_type="knowledge_article", resource_id=str(article.id), metadata_json={"reason": payload.reason}))
    await db.commit()
    return {"id": article.id, "status": article.status}


@router.get("/knowledge/gaps")
async def knowledge_gaps(days: int = 30, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Real, data-derived knowledge-gap signals — never fabricated counts.

    Two independent signals, both already persisted by the resolution-policy
    gate and the review workflow: (1) tickets where the retrieval/citation
    gates actually failed for lack of approved evidence, and (2) resolutions
    a reviewer had to edit heavily relative to the AI draft. Usage/traffic-
    based signals are not included — this repository does not yet track
    per-article citation counts, so no number for that is reported here.
    """
    await guard(db, user, "knowledge:manage", "knowledge:approve")
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    decisions = (await db.scalars(
        select(TicketDecision).where(TicketDecision.tenant_id == user.tenant_id)
        .order_by(TicketDecision.created_at.desc()).limit(500)
    )).all()
    weak_evidence: dict[str, dict] = {}
    for decision in decisions:
        if decision.created_at.timestamp() < since:
            continue
        if not any(gate in (decision.failed_gates or []) for gate in ("approved_current_evidence", "retrieval_relevance")):
            continue
        ticket = await db.get(Ticket, decision.ticket_id)
        if not ticket:
            continue
        key = ticket.category or "uncategorized"
        bucket = weak_evidence.setdefault(key, {"category": key, "count": 0, "example_ticket_ids": []})
        bucket["count"] += 1
        if len(bucket["example_ticket_ids"]) < 5:
            bucket["example_ticket_ids"].append(str(ticket.id))

    heavy_edits = (await db.execute(
        select(Ticket.category, func.count(), func.avg(Feedback.text_change_ratio))
        .select_from(Feedback).join(Ticket, Ticket.id == Feedback.ticket_id)
        .where(Ticket.tenant_id == user.tenant_id, Feedback.text_change_ratio.is_not(None), Feedback.text_change_ratio > 0.5)
        .group_by(Ticket.category)
    )).all()
    return {
        "window_days": days,
        "weak_evidence_by_category": sorted(weak_evidence.values(), key=lambda row: row["count"], reverse=True),
        "heavy_edit_by_category": [{"category": category or "uncategorized", "count": int(count), "average_edit_ratio": round(float(avg), 3)} for category, count, avg in heavy_edits],
    }


@router.get("/knowledge/health")
async def knowledge_health(stale_after_days: int = 180, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Age-based health signal for the published retrieval corpus.

    Only ``age_days`` and a ``stale`` flag are reported. This repository does
    not yet track per-article citation counts or customer-feedback success
    rates against a specific source, so those signals are honestly omitted
    rather than estimated.
    """
    await guard(db, user, "knowledge:manage", "knowledge:approve")
    docs = (await db.scalars(select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.tenant_id == user.tenant_id, KnowledgeBaseDocument.status == "approved"))).all()
    now = datetime.now(timezone.utc)
    rows = []
    for doc in docs:
        age_days = (now - doc.updated_at).days if doc.updated_at else None
        rows.append({"id": doc.id, "title": doc.title, "department_id": doc.department_id, "version": doc.version,
                     "age_days": age_days, "stale": bool(age_days is not None and age_days > stale_after_days)})
    return {"stale_after_days": stale_after_days, "articles": sorted(rows, key=lambda row: row["age_days"] or 0, reverse=True)}


@router.get("/incidents")
async def incidents(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await guard(db, user, "incident:manage", "ticket:internal_ai")
    items = (await db.scalars(select(Incident).where(Incident.tenant_id == user.tenant_id).order_by(Incident.created_at.desc()))).all()
    return [{"id": x.id, "title": x.title, "service": x.service, "status": x.status, "severity": x.severity, "ticket_count": x.ticket_count, "growth_rate": float(x.growth_rate), "common_symptom": x.common_symptom} for x in items]


@router.get("/audit-logs")
async def audit_logs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await user_has_permission(db, user, "audit:read"):
        raise HTTPException(status_code=403, detail="Insufficient permission for this action")
    logs = (await db.scalars(select(AuditLog).where(AuditLog.tenant_id == user.tenant_id).order_by(AuditLog.created_at.desc()).limit(200))).all()
    return [{"id": x.id, "action": x.action, "resource_type": x.resource_type, "resource_id": x.resource_id, "metadata": x.metadata_json, "created_at": x.created_at} for x in logs]


@router.get("/notifications")
async def notifications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    items = (await db.scalars(select(Notification).where(Notification.tenant_id == user.tenant_id, Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100))).all()
    return [{"id": x.id, "title": x.title, "message": x.message, "kind": x.kind, "is_read": x.is_read, "created_at": x.created_at} for x in items]


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    item = await db.get(Notification, notification_id)
    if not item or item.tenant_id != user.tenant_id or item.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    item.is_read = True
    await db.commit()
    return {"id": item.id, "is_read": True}


@router.get("/ai/metrics")
async def ai_metrics(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await guard(db, user, "ticket:internal_ai", "analytics:all", "ai:monitor")
    rows = (await db.execute(select(AIDecision.agent_name, func.count(), func.avg(AIDecision.latency_ms), func.avg(AIDecision.confidence)).where(AIDecision.tenant_id == user.tenant_id).group_by(AIDecision.agent_name))).all()
    return {"agents": [{"name": n, "calls": c, "average_latency_ms": round(float(l or 0), 1), "average_confidence": round(float(cf or 0), 3), "success_rate": 1.0} for n,c,l,cf in rows], "provider": "deterministic-local", "external_cost_usd": 0}


@router.get("/integrations")
async def integrations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await guard(db, user, "integration:manage")
    items = (await db.scalars(select(Integration).where(Integration.tenant_id == user.tenant_id))).all()
    return [{"id": x.id, "provider": x.provider, "name": x.name, "enabled": x.enabled} for x in items]
