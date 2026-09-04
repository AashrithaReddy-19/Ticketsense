from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.rbac import canonical_role
from app.models.ticket import Ticket
from app.models.user import User

def visibility_conditions(user:User,queue:str="all"):
    base=[Ticket.tenant_id==user.tenant_id,Ticket.deleted_at.is_(None)]; role=canonical_role(user.role)
    if role=="customer": scope=Ticket.submitted_by==user.id
    elif role=="support_agent":
        assigned=Ticket.assignee_id==user.id; dept=and_(Ticket.department_id==user.department_id,Ticket.assignee_id.is_(None)); general=and_(Ticket.department_id.is_(None),Ticket.routing_state=="manual_triage")
        scope={"assigned":assigned,"department_triage":dept,"general_triage":general,"escalated":and_(or_(assigned,dept),Ticket.status=="escalated")}.get(queue,or_(assigned,dept,general))
    elif role=="reviewer": scope=and_(Ticket.department_id==user.department_id,or_(Ticket.review_required.is_(True),Ticket.status=="pending_review"))
    elif role=="team_lead": scope=Ticket.department_id==user.department_id
    elif role=="system_admin": scope=True
    elif role=="auditor": scope=Ticket.sensitivity!="confidential"
    elif role=="knowledge_manager": scope=and_(Ticket.department_id==user.department_id,Ticket.routing_state=="knowledge_review")
    else: scope=False
    return and_(*base,scope)

def visible_ticket_query(user:User,queue:str="all"):
    return select(Ticket).where(visibility_conditions(user,queue))

async def get_visible_ticket(db:AsyncSession,user:User,ticket_id):
    ticket=await db.scalar(visible_ticket_query(user).where(Ticket.id==ticket_id))
    if not ticket: raise HTTPException(404,"Ticket not found")
    return ticket
