from uuid import UUID
import json
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,Field
from sqlalchemy import func,select,text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.dependencies import get_current_user
from app.models.platform import AuditLog
from app.models.ticket import Ticket
from app.models.ticket_history import TicketHistory
from app.models.user import User
from app.core.rbac import canonical_role,has_permission
from app.models.response_draft import ResponseDraft
from app.services.workflow import approve_draft,create_draft,locked_ticket,transition
from app.services.ticket_visibility import get_visible_ticket,visible_ticket_query
from app.services.sla import breach_risk

router=APIRouter(prefix="/api/queues",tags=["queues"])
class ReviewDecision(BaseModel): decision:str=Field(pattern="^(approve|modify|reject|return)$"); reason:str=Field(min_length=3,max_length=2000); final_response:str|None=None

def summary(t:Ticket):
    a=(t.confidence_features or {}).get("analysis",{}); score=float(t.confidence_score or 0)
    sla_state=breach_risk(t.sla_due_at,t.created_at)["status"] if t.sla_due_at else ("at_risk" if a.get("sla_risk",0)>=70 else "on_track")
    return {"id":t.id,"display_id":str(t.id)[:8].upper(),"title":t.subject,"requester_id":t.submitted_by,"department_id":t.department_id,"assignee_id":t.assignee_id,"status":t.status,"priority":t.priority,"sla_state":sla_state,"sla_due_at":t.sla_due_at,"created_at":t.created_at,"updated_at":t.updated_at,"analysis_status":t.analysis_status,"review_required":t.review_required,"review_reason":t.review_reason,"confidence_band":"high" if score>=.75 else "medium" if score>=.5 else "low","risk":a.get("risk","medium")}

@router.get("/{queue_type}")
async def queue(queue_type:str,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    role=canonical_role(user.role); allowed={"support_agent":{"assigned","department_triage","general_triage","all","escalated"},"reviewer":{"review"},"team_lead":{"all","escalated"},"knowledge_manager":{"knowledge"},"auditor":{"audit"}}
    if queue_type not in allowed.get(role,set()): raise HTTPException(403,"Queue is not authorized for this role")
    q=visible_ticket_query(user,"all" if queue_type in {"review","knowledge","audit"} else queue_type)
    total=await db.scalar(select(func.count()).select_from(q.subquery())); rows=(await db.scalars(q.order_by(Ticket.created_at.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return {"items":[summary(t) for t in rows],"page":page,"page_size":page_size,"total":total or 0,"queue_type":queue_type}

@router.post("/tickets/{ticket_id}/accept")
async def accept(ticket_id:UUID,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    if canonical_role(user.role)!="support_agent": raise HTTPException(403,"Agent role required")
    visible=await get_visible_ticket(db,user,ticket_id); ticket=await locked_ticket(db,visible.id,user.tenant_id)
    if ticket.assignee_id and ticket.assignee_id!=user.id: raise HTTPException(409,"Ticket is already assigned")
    ticket.assignee_id=user.id
    if ticket.status in {"routed","reopened","escalated"}: transition(db,ticket,user,"assigned","assignment_accepted",visibility="both")
    elif ticket.status!="assigned": raise HTTPException(409,"Ticket is not available for assignment")
    await db.commit(); await db.refresh(ticket); return summary(ticket)

@router.post("/reviews/{ticket_id}")
async def review(ticket_id:UUID,payload:ReviewDecision,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    if not has_permission(user.role,"review:manage"): raise HTTPException(403,"Reviewer permission required")
    visible=await get_visible_ticket(db,user,ticket_id); ticket=await locked_ticket(db,visible.id,user.tenant_id); analysis=(ticket.confidence_features or {}).get("analysis",{})
    draft=await db.get(ResponseDraft,ticket.latest_draft_id) if ticket.latest_draft_id else None
    if not draft or draft.status!="submitted_for_review": raise HTTPException(409,"A submitted engineer response is required")
    await db.execute(text("""INSERT INTO human_reviews(tenant_id,ticket_id,reviewer_id,decision,reason,original_ai_draft,final_response,confidence_snapshot,risk_snapshot,evidence_snapshot) VALUES(:tid,:ticket,:reviewer,:decision,:reason,:draft,:final,:confidence,CAST(:risk AS jsonb),CAST(:evidence AS jsonb))"""),{"tid":user.tenant_id,"ticket":ticket.id,"reviewer":user.id,"decision":payload.decision,"reason":payload.reason,"draft":ticket.ai_draft_reply,"final":payload.final_response,"confidence":ticket.confidence_score,"risk":json.dumps({"risk":analysis.get("risk","medium")}),"evidence":json.dumps(analysis.get("evidence",[]))})
    if payload.decision in {"approve","modify"}:
        approved=await approve_draft(db,ticket,user,draft,payload.final_response,payload.reason,payload.decision=="modify"); ticket.review_required=False
    else:
        draft.status="rejected" if payload.decision=="reject" else "changes_requested"; transition(db,ticket,user,"changes_requested",f"review_{payload.decision}",payload.reason,"internal",draft.version_number); ticket.review_required=False
    await db.commit(); await db.refresh(ticket); return {"stored":True,"ticket":summary(ticket)}
