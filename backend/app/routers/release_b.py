from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import canonical_role, has_permission
from app.database import get_db
from app.dependencies import get_current_user
from app.models.ai_draft import AIDraft
from app.models.ai_pipeline import ClaimValidation, PipelineExecution, PipelineStage, TechnicalEntity
from app.models.platform import AuditLog
from app.models.ticket import Ticket
from app.models.user import User
from app.services.ticket_visibility import get_visible_ticket

router = APIRouter(prefix="/api/tickets", tags=["explainable-ai"])
STAFF_ROLES = {"support_agent", "reviewer", "team_lead", "system_admin", "auditor"}


class EntityCorrection(BaseModel):
    normalized_value: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=3, max_length=1000)


async def internal_ticket(ticket_id: UUID, user: User, db: AsyncSession) -> Ticket:
    if canonical_role(user.role) not in STAFF_ROLES:
        raise HTTPException(403, "Staff AI visibility required")
    return await get_visible_ticket(db, user, ticket_id)


@router.get("/{ticket_id}/pipeline-trace")
async def pipeline_trace(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket = await internal_ticket(ticket_id, user, db)
    execution = await db.scalar(select(PipelineExecution).where(PipelineExecution.ticket_id == ticket.id, PipelineExecution.tenant_id == user.tenant_id).order_by(PipelineExecution.started_at.desc()).limit(1))
    if not execution:
        return {"execution": None, "stages": [], "claims": []}
    stages = list((await db.scalars(select(PipelineStage).where(PipelineStage.execution_id == execution.id).order_by(PipelineStage.sequence_number))).all())
    claims = list((await db.scalars(select(ClaimValidation).where(ClaimValidation.execution_id == execution.id).order_by(ClaimValidation.created_at))).all())
    return {"execution": {"id":execution.id,"pipeline_version":execution.pipeline_version,"trigger_type":execution.trigger_type,"status":execution.status,"started_at":execution.started_at,"completed_at":execution.completed_at,"total_duration_ms":execution.total_duration_ms,"failure_stage":execution.failure_stage,"fallback_used":execution.fallback_used,"correlation_id":execution.correlation_id},
            "stages":[{"id":row.id,"stage_name":row.stage_name,"sequence_number":row.sequence_number,"status":row.status,"output_summary":row.output_summary,"provider_name":row.provider_name,"provider_version":row.provider_version,"confidence":row.confidence,"started_at":row.started_at,"completed_at":row.completed_at,"duration_ms":row.duration_ms,"error_category":row.error_category,"safe_error_summary":row.safe_error_summary,"fallback_used":row.fallback_used,"metadata":row.metadata_json} for row in stages],
            "claims":[{"claim_text":row.claim_text,"citation_id":row.citation_id,"validation_status":row.validation_status,"risk_level":row.risk_level,"reason":row.reason,"validator_version":row.validator_version} for row in claims]}


@router.get("/{ticket_id}/technical-entities")
async def technical_entities(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket = await internal_ticket(ticket_id, user, db)
    rows = list((await db.scalars(select(TechnicalEntity).where(TechnicalEntity.ticket_id == ticket.id, TechnicalEntity.tenant_id == user.tenant_id).order_by(TechnicalEntity.start_offset, TechnicalEntity.created_at))).all())
    return [{"id":row.id,"entity_type":row.entity_type,"raw_value":row.raw_value,"normalized_value":row.normalized_value,"source":row.source,"extraction_method":row.extraction_method,"confidence":row.confidence,"start_offset":row.start_offset,"end_offset":row.end_offset,"validation_status":row.validation_status,"corrected_from_id":row.corrected_from_id,"created_at":row.created_at} for row in rows]


@router.post("/{ticket_id}/technical-entities/{entity_id}/corrections", status_code=201)
async def correct_entity(ticket_id: UUID, entity_id: UUID, payload: EntityCorrection, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not (has_permission(user.role,"ticket:update") or has_permission(user.role,"review:manage")):
        raise HTTPException(403,"Entity correction permission required")
    ticket=await internal_ticket(ticket_id,user,db)
    original=await db.scalar(select(TechnicalEntity).where(TechnicalEntity.id==entity_id,TechnicalEntity.ticket_id==ticket.id,TechnicalEntity.tenant_id==user.tenant_id))
    if not original: raise HTTPException(404,"Technical entity not found")
    correction=TechnicalEntity(tenant_id=user.tenant_id,ticket_id=ticket.id,entity_type=original.entity_type,raw_value=original.raw_value,normalized_value=payload.normalized_value.strip(),source=original.source,extraction_method="human-correction",confidence=1.0,start_offset=original.start_offset,end_offset=original.end_offset,validation_status="corrected",corrected_from_id=original.id)
    db.add(correction);db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="technical_entity.corrected",resource_type="ticket",resource_id=str(ticket.id),metadata_json={"entity_id":str(original.id),"reason":payload.reason}));await db.commit();await db.refresh(correction)
    return {"id":correction.id,"entity_type":correction.entity_type,"raw_value":correction.raw_value,"normalized_value":correction.normalized_value,"validation_status":correction.validation_status,"corrected_from_id":correction.corrected_from_id}


@router.get("/{ticket_id}/explanation")
async def explanation(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket=await internal_ticket(ticket_id,user,db);features=ticket.confidence_features or {};analysis=features.get("analysis",{});confidence=features.get("confidence_model",{})
    draft=await db.scalar(select(AIDraft).where(AIDraft.ticket_id==ticket.id,AIDraft.tenant_id==user.tenant_id))
    entities=list((await db.scalars(select(TechnicalEntity).where(TechnicalEntity.ticket_id==ticket.id,TechnicalEntity.corrected_from_id.is_(None)).order_by(TechnicalEntity.start_offset))).all())
    evidence=draft.evidence if draft else [];scores=sorted([float(item.get("similarity",0)) for item in evidence],reverse=True);validation=draft.validation_details if draft else {}
    score=float(ticket.confidence_score) if ticket.confidence_score is not None else None;low=confidence.get("low_threshold");high=confidence.get("high_threshold")
    positives=[];risks=[]
    if scores: positives.append("Approved evidence was retrieved")
    if validation.get("valid"): positives.append("All referenced citation IDs passed scope validation")
    if not evidence: risks.append("No approved evidence is currently available")
    if validation.get("grounding",{}).get("blocked"): risks.append("Grounding validation blocked response readiness")
    return {"predicted_department":analysis.get("department") or str(ticket.department_id),"candidate_department_probabilities":analysis.get("department_probabilities"),"predicted_category":analysis.get("category"),"predicted_priority":ticket.priority,"important_keywords":analysis.get("keywords"),"technical_entities":[{"type":row.entity_type,"value":row.normalized_value} for row in entities],"routing_reason":analysis.get("routing_reason") or analysis.get("decision_reason"),"assignment_reason":ticket.assignment_reason,"top_retrieval_similarity":scores[0] if scores else None,"retrieval_score_gap":scores[0]-scores[1] if len(scores)>1 else None,"valid_evidence_count":len(evidence),"citation_coverage":validation.get("citation_coverage"),"confidence_score":score,"low_threshold":low,"high_threshold":high,"confidence_band":confidence.get("gate"),"positive_factors":positives,"risk_factors":risks,"grounding_status":validation.get("grounding",{}).get("overall_status"),"human_review_decision":validation.get("human_review_decision") or ticket.review_reason,"disclaimer":"Predictions and rule explanations are decision support, not confirmed facts."}
