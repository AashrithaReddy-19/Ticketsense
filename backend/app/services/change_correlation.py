"""V2 Phase 15: change-aware incident correlation.

Surfaces real, timestamped changes already made in this tenant — feature
flag toggles, AI model promotions/rollbacks, and knowledge article edits —
that happened shortly before a given incident began. This is temporal
proximity only, computed from real audit rows, never a confirmed cause:
every hypothesis returned here carries an explicit note that a human must
investigate before acting on it. Nothing is scored, ranked by "likelihood",
or otherwise dressed up to look more certain than "this happened first."
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.platform import Incident
from app.models.v2_governance import FeatureFlag, FeatureFlagAudit, ModelDeployment

LOOKBACK_HOURS = 72
NOT_A_CONFIRMED_CAUSE_NOTE = "Temporal proximity only — not a confirmed cause. Requires human investigation before acting."


@dataclass
class ChangeRecord:
    change_type: str
    description: str
    department_id: UUID | None
    occurred_at: datetime


async def _recent_feature_flag_changes(db: AsyncSession, tenant_id: UUID, since: datetime, until: datetime) -> list[ChangeRecord]:
    rows = (await db.execute(
        select(FeatureFlagAudit.action, FeatureFlagAudit.created_at, FeatureFlag.key)
        .join(FeatureFlag, FeatureFlag.id == FeatureFlagAudit.flag_id)
        .where(
            or_(FeatureFlagAudit.tenant_id == tenant_id, FeatureFlagAudit.tenant_id.is_(None)),
            FeatureFlagAudit.created_at >= since, FeatureFlagAudit.created_at <= until,
        )
    )).all()
    return [ChangeRecord("feature_flag", f"Feature flag '{key}' was {action}", None, created_at) for action, created_at, key in rows]


async def _recent_model_deployment_changes(db: AsyncSession, tenant_id: UUID, since: datetime, until: datetime) -> list[ChangeRecord]:
    rows = (await db.scalars(
        select(ModelDeployment).where(ModelDeployment.tenant_id == tenant_id, ModelDeployment.created_at >= since, ModelDeployment.created_at <= until)
    )).all()
    return [ChangeRecord("model_deployment", f"AI model for task '{row.task_type}' was {row.action}d", None, row.created_at) for row in rows]


async def _recent_knowledge_article_changes(db: AsyncSession, tenant_id: UUID, since: datetime, until: datetime) -> list[ChangeRecord]:
    rows = (await db.scalars(
        select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.tenant_id == tenant_id, KnowledgeBaseDocument.updated_at >= since, KnowledgeBaseDocument.updated_at <= until)
    )).all()
    return [ChangeRecord("knowledge_article", f"Knowledge article '{row.title}' was updated to version {row.version}", row.department_id, row.updated_at) for row in rows]


async def correlate_incident_with_recent_changes(db: AsyncSession, incident: Incident) -> list[dict]:
    since = incident.created_at - timedelta(hours=LOOKBACK_HOURS)
    changes: list[ChangeRecord] = []
    changes += await _recent_feature_flag_changes(db, incident.tenant_id, since, incident.created_at)
    changes += await _recent_model_deployment_changes(db, incident.tenant_id, since, incident.created_at)
    changes += await _recent_knowledge_article_changes(db, incident.tenant_id, since, incident.created_at)

    hypotheses = []
    for change in changes:
        # A department-scoped change in a different department than the incident is not a
        # plausible hypothesis; a tenant-wide change (department_id is None) is always kept.
        if change.department_id is not None and incident.department_id is not None and change.department_id != incident.department_id:
            continue
        hours_before = (incident.created_at - change.occurred_at).total_seconds() / 3600
        hypotheses.append({
            "change_type": change.change_type, "description": change.description,
            "occurred_at": change.occurred_at.isoformat(), "hours_before_incident": round(hours_before, 2),
            "note": NOT_A_CONFIRMED_CAUSE_NOTE,
        })
    hypotheses.sort(key=lambda h: h["hours_before_incident"])
    return hypotheses
