from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ai_draft import AIDraft
from app.models.ticket import Ticket
from app.models.ticket_attachment import TicketAttachment
from app.config import settings
from app.services.pipeline_metrics import StageTiming, persist_stage_timings, stage_timer
from app.models.ai_pipeline import ClaimValidation, PipelineExecution, PipelineStage, TechnicalEntity
from app.models.v2_governance import AIUsageEvent

async def generate_and_store_draft(db:AsyncSession,ticket:Ticket,article_version:str="1.0")->AIDraft:
    """Invoke the graph and idempotently replace the ticket's active draft snapshot.

    Uses an atomic INSERT ... ON CONFLICT (ticket_id) DO UPDATE rather than a
    select-then-insert, since two concurrent generate requests for the same ticket
    (e.g. a client retry after a slow response) would otherwise both see no existing
    row and race on the uq_ai_drafts_ticket unique constraint.
    """
    from ai.graph import PIPELINE_VERSION, PipelineStageError, graph
    attachment=await db.scalar(select(TicketAttachment).where(TicketAttachment.ticket_id==ticket.id,TicketAttachment.tenant_id==ticket.tenant_id))
    snapshots=ticket.confidence_features or {};initial_analysis=snapshots.get("analysis",{});initial_confidence=snapshots.get("confidence_model",{})
    state={"ticket_id":str(ticket.id),"tenant_id":str(ticket.tenant_id),"department_id":str(ticket.department_id) if ticket.department_id else "","subject":ticket.subject,"description":ticket.description,"article_version":article_version,
           "initial_confidence_score":float(ticket.confidence_score or .5),
           "classification_probability":float(initial_analysis.get("classification_probability",initial_analysis.get("confidence",ticket.confidence_score or .5))),
           "classification_margin":float(initial_analysis.get("classification_margin",0)),
           "low_confidence_threshold":float(initial_confidence.get("low_threshold",.55)),
           "high_confidence_threshold":float(initial_confidence.get("high_threshold",.80))}
    if attachment:
        state.update({"attachment_id":str(attachment.id),"attachment_type":attachment.detected_mime_type,"extraction_status":attachment.extraction_status,"attachment_text":(attachment.sanitized_text or "")[:settings.attachment_context_chars] if attachment.extraction_status=="ready" else "","extraction_method":attachment.extraction_method or "unavailable","ocr_confidence":attachment.ocr_confidence,"ocr_confidence_available":attachment.ocr_confidence_available,"extraction_warnings":attachment.warnings,"attachment_truncated":attachment.truncated})
    timings:list[StageTiming]=[]; execution_started=datetime.now(timezone.utc); execution_clock=monotonic(); correlation_id=uuid4()
    execution=PipelineExecution(tenant_id=ticket.tenant_id,ticket_id=ticket.id,pipeline_version=PIPELINE_VERSION,trigger_type="draft_generation",status="running",started_at=execution_started,fallback_used=False,correlation_id=correlation_id)
    db.add(execution);await db.flush()
    try:
        with stage_timer("evidence_retrieval_and_drafting",timings,provider_version=state.get("model")): result=await graph.ainvoke(state)
    except Exception as exc:
        result={**state,"generation_status":"failed","generation_error":type(exc).__name__,"citation_validation":{"valid":False,"validation_errors":["Pipeline execution failed"]},"retrieved_chunks":[],"citations":[]}
        execution.status="failed";execution.failure_stage=getattr(exc,"stage_name",None)
        if isinstance(exc,PipelineStageError):
            for stage in exc.completed_trace:
                db.add(PipelineStage(execution_id=execution.id,stage_name=stage["stage_name"],sequence_number=stage["sequence_number"],status=stage["status"],input_summary=stage.get("input_summary"),output_summary=stage.get("output_summary"),provider_name=stage.get("provider_name"),provider_version=stage.get("provider_version"),confidence=stage.get("confidence"),started_at=datetime.fromisoformat(stage["started_at"]),completed_at=datetime.fromisoformat(stage["completed_at"]),duration_ms=stage["duration_ms"],fallback_used=stage.get("fallback_used",False),metadata_json=stage.get("metadata",{})))
            started=datetime.fromisoformat(exc.started_at);db.add(PipelineStage(execution_id=execution.id,stage_name=exc.stage_name,sequence_number=exc.sequence_number,status="failed",input_summary="Safe ticket state",output_summary="Stage failed",provider_name="deterministic",provider_version=PIPELINE_VERSION,started_at=started,completed_at=datetime.now(timezone.utc),duration_ms=exc.duration_ms,error_category=exc.error_category,safe_error_summary="Stage could not complete",fallback_used=False,metadata_json={}))
    else:
        stage_rows=result.get("stage_trace",[])
        execution.fallback_used=any(bool(stage.get("fallback_used")) for stage in stage_rows)
        blocked=result.get("generation_status") in {"failed","failed_validation","blocked_validation"}
        execution.status="blocked" if blocked else "completed_with_fallback" if execution.fallback_used else "completed"
        for stage in stage_rows:
            db.add(PipelineStage(execution_id=execution.id,stage_name=stage["stage_name"],sequence_number=stage["sequence_number"],status=stage["status"],input_summary=stage.get("input_summary"),output_summary=stage.get("output_summary"),provider_name=stage.get("provider_name"),provider_version=stage.get("provider_version"),confidence=stage.get("confidence"),started_at=datetime.fromisoformat(stage["started_at"]),completed_at=datetime.fromisoformat(stage["completed_at"]),duration_ms=stage["duration_ms"],fallback_used=stage.get("fallback_used",False),metadata_json=stage.get("metadata",{})))
    execution.completed_at=datetime.now(timezone.utc);execution.total_duration_ms=round((monotonic()-execution_clock)*1000)
    persist_stage_timings(db,ticket.tenant_id,ticket.id,correlation_id,timings)
    for item in result.get("technical_entities",[]):
        existing=await db.scalar(select(TechnicalEntity.id).where(TechnicalEntity.ticket_id==ticket.id,TechnicalEntity.entity_type==item["entity_type"],TechnicalEntity.normalized_value==item["normalized_value"],TechnicalEntity.source==item["source"],TechnicalEntity.corrected_from_id.is_(None)))
        if not existing: db.add(TechnicalEntity(tenant_id=ticket.tenant_id,ticket_id=ticket.id,**item))
    grounding=result.get("grounding_validation",{})
    for claim in grounding.get("claims",[]): db.add(ClaimValidation(tenant_id=ticket.tenant_id,ticket_id=ticket.id,execution_id=execution.id,**claim))
    validation={**result.get("citation_validation",{}),"grounding":grounding,"human_review_decision":result.get("human_review_decision"),"confidence_band":result.get("confidence_band"),"confidence_score":result.get("confidence_score"),"confidence_features":result.get("confidence_features",{}),"confidence_model_version":result.get("confidence_model_version"),"confidence_fallback_used":result.get("fallback_used",False),"low_threshold":state["low_confidence_threshold"],"high_threshold":state["high_confidence_threshold"],"execution_id":str(execution.id)}
    values=dict(
        tenant_id=ticket.tenant_id,
        ticket_id=ticket.id,
        department_id=result.get("department_id") or ticket.department_id,
        article_version=article_version,
        draft_text=result.get("draft_reply"),
        citations=result.get("citations",[]),
        evidence=result.get("retrieved_chunks",[]),
        provider=result.get("provider"),
        model=result.get("model"),
        generation_status=result.get("generation_status","failed"),
        citation_validation_status="valid" if validation.get("valid") else "invalid",
        validation_details=validation,
        generation_error=result.get("generation_error"),
        insufficient_evidence=bool(result.get("insufficient_evidence")),
    )
    stmt=pg_insert(AIDraft).values(**values,attempt_count=1)
    update_columns={key:stmt.excluded[key] for key in values if key not in ("tenant_id","ticket_id")}
    update_columns["attempt_count"]=AIDraft.attempt_count+1
    stmt=stmt.on_conflict_do_update(index_elements=[AIDraft.ticket_id],set_=update_columns).returning(AIDraft)
    draft=(await db.execute(stmt)).scalar_one()
    token_metadata=result.get("provider_token_metadata") or {}
    db.add(AIUsageEvent(
        tenant_id=ticket.tenant_id,ticket_id=ticket.id,task_type="grounded_draft",
        provider=result.get("provider") or "pipeline_unavailable",model_version=result.get("model") or PIPELINE_VERSION,
        latency_ms=int(result.get("provider_latency_ms") or execution.total_duration_ms or 0),
        input_tokens=token_metadata.get("input_tokens"),output_tokens=token_metadata.get("output_tokens"),
        estimated_cost_usd=token_metadata.get("estimated_cost_usd"),cache_hit=bool(token_metadata.get("cache_hit",False)),
        success=execution.status in {"completed","completed_with_fallback"},error_category=execution.failure_stage,
        correlation_id=correlation_id,metadata_json={"pipeline_version":PIPELINE_VERSION,"cost_source":"provider_metadata" if token_metadata.get("estimated_cost_usd") is not None else "unavailable"},
    ))
    if result.get("confidence_score") is not None:
        ticket.confidence_score=result["confidence_score"]
        ticket.confidence_features={**snapshots,"confidence_model":{**initial_confidence,"score":result["confidence_score"],"features":result.get("confidence_features",{}),"model_version":result.get("confidence_model_version"),"trained_artifact":result.get("confidence_trained_artifact",False),"gate":result.get("confidence_band"),"low_threshold":state["low_confidence_threshold"],"high_threshold":state["high_confidence_threshold"]}}
    if validation.get("valid") and not grounding.get("blocked",False): ticket.ai_draft_reply=draft.draft_text
    return draft

def serialize_draft(draft:AIDraft)->dict:
    return {"ticket_id":draft.ticket_id,"draft_text":draft.draft_text if draft.citation_validation_status=="valid" else None,"citations":draft.citations,"evidence":draft.evidence,"provider":draft.provider,"model":draft.model,"generation_status":draft.generation_status,"citation_validation_status":draft.citation_validation_status,"validation":draft.validation_details,"generation_error":"Generation failed" if draft.generation_error else None,"insufficient_evidence":draft.insufficient_evidence,"attempt_count":draft.attempt_count,"created_at":draft.created_at,"updated_at":draft.updated_at}
