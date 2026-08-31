from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.platform import AIDecision, AuditLog, Incident, Integration, KnowledgeArticle, Notification
from app.models.ticket import Ticket
from app.models.user import User
from app.core.rbac import has_permission

router = APIRouter(prefix="/api", tags=["platform"])


def guard(user: User, roles: set[str]) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="Insufficient role for this action")


class ArticleCreate(BaseModel):
    title: str = Field(min_length=4, max_length=255)
    body: str = Field(min_length=20)
    source_ticket_ids: list[str] = []


@router.get("/knowledge")
async def knowledge(q: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.tenant_id == user.tenant_id)
    if q: query = query.where(KnowledgeBaseDocument.title.ilike(f"%{q}%") | KnowledgeBaseDocument.content.ilike(f"%{q}%"))
    docs = (await db.scalars(query.order_by(KnowledgeBaseDocument.updated_at.desc()).limit(50))).all()
    return [{"id": d.id, "title": d.title, "excerpt": d.content[:240], "source": d.source_url, "updated_at": d.updated_at} for d in docs]


@router.post("/knowledge/articles/generate")
async def generate_article(payload: ArticleCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    guard(user, {"support_agent", "manager", "knowledge_manager", "enterprise_admin", "department_engineer", "admin"})
    article = KnowledgeArticle(tenant_id=user.tenant_id, department_id=user.department_id, title=payload.title, body=payload.body, source_ticket_ids=payload.source_ticket_ids, status="pending_review")
    db.add(article); await db.flush()
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="knowledge.generated", resource_type="knowledge_article", resource_id=str(article.id), metadata_json={}))
    await db.commit(); await db.refresh(article)
    return {"id": article.id, "status": article.status, "title": article.title}


@router.post("/knowledge/articles/{article_id}/approve")
async def approve_article(article_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    guard(user, {"manager", "knowledge_manager", "enterprise_admin", "admin"})
    article = await db.get(KnowledgeArticle, article_id)
    if not article or article.tenant_id != user.tenant_id: raise HTTPException(404, "Article not found")
    article.status = "published"; article.approved_by = user.id
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="knowledge.approved", resource_type="knowledge_article", resource_id=str(article.id), metadata_json={}))
    await db.commit()
    return {"id": article.id, "status": article.status}


@router.get("/incidents")
async def incidents(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    items = (await db.scalars(select(Incident).where(Incident.tenant_id == user.tenant_id).order_by(Incident.created_at.desc()))).all()
    return [{"id": x.id, "title": x.title, "service": x.service, "status": x.status, "severity": x.severity, "ticket_count": x.ticket_count, "growth_rate": float(x.growth_rate), "common_symptom": x.common_symptom} for x in items]


@router.get("/audit-logs")
async def audit_logs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not has_permission(user.role, "audit:read"):
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
    guard(user, {"support_agent", "department_engineer", "manager", "enterprise_admin", "ai_admin", "admin"})
    rows = (await db.execute(select(AIDecision.agent_name, func.count(), func.avg(AIDecision.latency_ms), func.avg(AIDecision.confidence)).where(AIDecision.tenant_id == user.tenant_id).group_by(AIDecision.agent_name))).all()
    return {"agents": [{"name": n, "calls": c, "average_latency_ms": round(float(l or 0), 1), "average_confidence": round(float(cf or 0), 3), "success_rate": 1.0} for n,c,l,cf in rows], "provider": "deterministic-local", "external_cost_usd": 0}


@router.get("/integrations")
async def integrations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    guard(user, {"enterprise_admin", "admin"})
    items = (await db.scalars(select(Integration).where(Integration.tenant_id == user.tenant_id))).all()
    return [{"id": x.id, "provider": x.provider, "name": x.name, "enabled": x.enabled} for x in items]
