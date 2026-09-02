from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ai_draft import AIDraft
from app.models.ticket import Ticket
from app.models.ticket_attachment import TicketAttachment
from app.config import settings

async def generate_and_store_draft(db:AsyncSession,ticket:Ticket,article_version:str="1.0")->AIDraft:
    """Invoke the graph and idempotently replace the ticket's active draft snapshot.

    Uses an atomic INSERT ... ON CONFLICT (ticket_id) DO UPDATE rather than a
    select-then-insert, since two concurrent generate requests for the same ticket
    (e.g. a client retry after a slow response) would otherwise both see no existing
    row and race on the uq_ai_drafts_ticket unique constraint.
    """
    from ai.graph import graph
    attachment=await db.scalar(select(TicketAttachment).where(TicketAttachment.ticket_id==ticket.id,TicketAttachment.tenant_id==ticket.tenant_id))
    state={"ticket_id":str(ticket.id),"tenant_id":str(ticket.tenant_id),"department_id":str(ticket.department_id) if ticket.department_id else "","subject":ticket.subject,"description":ticket.description,"article_version":article_version}
    if attachment:
        state.update({"attachment_id":str(attachment.id),"attachment_type":attachment.detected_mime_type,"extraction_status":attachment.extraction_status,"attachment_text":(attachment.sanitized_text or "")[:settings.attachment_context_chars] if attachment.extraction_status=="ready" else "","extraction_method":attachment.extraction_method or "unavailable","ocr_confidence":attachment.ocr_confidence,"ocr_confidence_available":attachment.ocr_confidence_available,"extraction_warnings":attachment.warnings,"attachment_truncated":attachment.truncated})
    try: result=await graph.ainvoke(state)
    except Exception as exc:
        result={**state,"generation_status":"failed","generation_error":type(exc).__name__,"citation_validation":{"valid":False,"validation_errors":["Pipeline execution failed"]},"retrieved_chunks":[],"citations":[]}
    validation=result.get("citation_validation",{})
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
    if validation.get("valid"): ticket.ai_draft_reply=draft.draft_text
    return draft

def serialize_draft(draft:AIDraft)->dict:
    return {"ticket_id":draft.ticket_id,"draft_text":draft.draft_text if draft.citation_validation_status=="valid" else None,"citations":draft.citations,"evidence":draft.evidence,"provider":draft.provider,"model":draft.model,"generation_status":draft.generation_status,"citation_validation_status":draft.citation_validation_status,"validation":draft.validation_details,"generation_error":"Generation failed" if draft.generation_error else None,"insufficient_evidence":draft.insufficient_evidence,"attempt_count":draft.attempt_count,"created_at":draft.created_at,"updated_at":draft.updated_at}
