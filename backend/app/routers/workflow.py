from uuid import UUID
from difflib import SequenceMatcher
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import canonical_role, has_permission, is_customer
from app.core.security import hash_password
from app.database import get_db
from app.dependencies import get_current_user
from app.models.response_draft import EngineerDepartment, EngineerSpecialization, ResponseDraft, TicketEvent
from app.models.department import Department
from app.models.feedback import Feedback
from app.models.platform import AuditLog
from app.models.operations import DepartmentConfidencePolicy
from app.models.enterprise import EngineerProfile, EngineerSkill
from datetime import datetime, timezone
from app.models.ticket import Ticket
from app.models.user import User
from app.services.ticket_visibility import get_visible_ticket
from app.services.workflow import approve_draft, assign_ticket, create_draft, ensure_response_ready, locked_ticket, record_event, transition

router = APIRouter(prefix="/api", tags=["ticket-workflow"])


class AssignRequest(BaseModel):
    engineer_id: UUID
    comment: str | None = Field(default=None, max_length=2000)


class DraftRequest(BaseModel):
    content: str = Field(min_length=10, max_length=20000)
    based_on_draft_id: UUID | None = None
    citations: list = Field(default_factory=list)


class CommentRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class ReviewRequest(BaseModel):
    action: str = Field(pattern="^(approve|modify_and_approve|request_changes|reject|escalate)$")
    response_content: str | None = Field(default=None, max_length=20000)
    review_comment: str = Field(min_length=3, max_length=2000)
    customer_visible_note: str | None = Field(default=None, max_length=1000)


class EngineerCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    department_id: UUID
    specializations: list[str] = Field(default_factory=list, max_length=20)
    is_available: bool = True
    max_active_workload: int = Field(default=10, ge=1, le=100)


class EngineerUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    department_id: UUID | None = None
    is_active: bool | None = None
    specializations: list[str] | None = Field(default=None, max_length=20)
    is_available: bool | None = None
    max_active_workload: int | None = Field(default=None, ge=1, le=100)


class ConfidencePolicyRequest(BaseModel):
    low_threshold: float = Field(ge=0, le=1)
    high_threshold: float = Field(ge=0, le=1)
    reason: str | None = Field(default=None, max_length=1000)


def draft_json(draft: ResponseDraft):
    return {"id": draft.id, "ticket_id": draft.ticket_id, "version_number": draft.version_number, "content": draft.content, "author_type": draft.author_type, "creator_role":draft.creator_role,"created_by_user_id": draft.created_by_user_id, "based_on_draft_id": draft.based_on_draft_id, "citations": draft.citations, "status": draft.status,"confidence_score":draft.confidence_score,"citation_validation_status":draft.citation_validation_status,"validation":draft.validation_details,"is_final":draft.is_final,"created_at": draft.created_at, "updated_at": draft.updated_at}


def _citation_keys(citations: list) -> set[str]:
    return {json.dumps(item, sort_keys=True, default=str) for item in citations}


def compare_drafts(earlier: ResponseDraft, later: ResponseDraft) -> dict:
    before, after = earlier.content.split(), later.content.split()
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    changes = []
    added = removed = 0
    for operation, i1, i2, j1, j2 in matcher.get_opcodes():
        if operation == "equal":
            continue
        added += j2 - j1
        removed += i2 - i1
        changes.append({"operation": operation, "before": " ".join(before[i1:i2]), "after": " ".join(after[j1:j2])})
    old_citations, new_citations = _citation_keys(earlier.citations), _citation_keys(later.citations)
    return {"from_version": earlier.version_number, "to_version": later.version_number,
            "from_author_type": earlier.author_type, "to_author_type": later.author_type,
            "edit_percentage": round((1 - matcher.ratio()) * 100, 2),
            "added_word_count": added, "removed_word_count": removed, "changes": changes,
            "citations_added": [json.loads(value) for value in sorted(new_citations - old_citations)],
            "citations_removed": [json.loads(value) for value in sorted(old_citations - new_citations)]}


def require(permission: str, user: User) -> None:
    if not has_permission(user.role, permission):
        raise HTTPException(403, f"Permission required: {permission}")


@router.get("/tickets/{ticket_id}/timeline")
async def timeline(ticket_id: UUID, page:int=Query(1,ge=1),page_size:int=Query(100,ge=1,le=200),user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket = await get_visible_ticket(db, user, ticket_id)
    query = select(TicketEvent).where(TicketEvent.ticket_id == ticket.id, TicketEvent.tenant_id == user.tenant_id)
    if is_customer(user.role): query = query.where(TicketEvent.visibility.in_(["customer", "both"]))
    events = (await db.scalars(query.order_by(TicketEvent.created_at).offset((page-1)*page_size).limit(page_size))).all()
    customer = is_customer(user.role)
    return [{"id": e.id, "event_type": e.event_type, "old_status": None if customer else e.old_status, "new_status": e.new_status, "comment": e.comment, "draft_version": None if customer else e.draft_version, "actor_role": None if customer else e.actor_role,"old_assignee_id":None if customer else e.old_assignee_id,"new_assignee_id":None if customer else e.new_assignee_id,"correlation_id":None if customer else e.correlation_id,"metadata":{} if customer else e.metadata_json,"created_at": e.created_at, "visibility": e.visibility} for e in events]


@router.get("/tickets/{ticket_id}/drafts")
async def drafts(ticket_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("ticket:internal_ai", user)
    ticket = await get_visible_ticket(db, user, ticket_id)
    rows = (await db.scalars(select(ResponseDraft).where(ResponseDraft.ticket_id == ticket.id, ResponseDraft.tenant_id == user.tenant_id).order_by(ResponseDraft.version_number.desc()))).all()
    return [draft_json(row) for row in rows]


@router.get("/tickets/{ticket_id}/draft-comparison")
async def draft_comparison(ticket_id: UUID, from_version: int | None = Query(None, ge=1), to_version: int | None = Query(None, ge=1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("ticket:internal_ai", user)
    ticket = await get_visible_ticket(db, user, ticket_id)
    rows = list((await db.scalars(select(ResponseDraft).where(ResponseDraft.ticket_id == ticket.id, ResponseDraft.tenant_id == user.tenant_id).order_by(ResponseDraft.version_number))).all())
    if len(rows) < 2:
        raise HTTPException(404, "At least two response versions are required")
    by_version = {row.version_number: row for row in rows}
    later = by_version.get(to_version) if to_version is not None else rows[-1]
    if not later:
        raise HTTPException(404, "Response version not found")
    earlier = by_version.get(from_version) if from_version is not None else next((row for row in reversed(rows) if row.version_number < later.version_number), None)
    if not earlier:
        raise HTTPException(404, "Previous response version not found")
    if earlier.version_number >= later.version_number:
        raise HTTPException(422, "from_version must be earlier than to_version")
    return compare_drafts(earlier, later)


@router.post("/tickets/{ticket_id}/assign")
async def assign(ticket_id: UUID, payload: AssignRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("ticket:assign", user); visible = await get_visible_ticket(db, user, ticket_id); ticket = await locked_ticket(db, visible.id, user.tenant_id)
    engineer = await db.get(User, payload.engineer_id)
    if not engineer: raise HTTPException(404, "Engineer not found")
    await assign_ticket(db, ticket, user, engineer, payload.comment); await db.commit(); await db.refresh(ticket)
    return {"ticket_id": ticket.id, "status": ticket.status, "assignee_id": ticket.assignee_id, "updated_at": ticket.updated_at}


@router.post("/tickets/{ticket_id}/start-work")
async def start_work(ticket_id: UUID, payload: CommentRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("ticket:update", user); visible = await get_visible_ticket(db, user, ticket_id); ticket = await locked_ticket(db, visible.id, user.tenant_id)
    if canonical_role(user.role) == "support_agent" and ticket.assignee_id != user.id: raise HTTPException(403, "Only the assigned engineer can start work")
    transition(db, ticket, user, "in_progress", "work_started", payload.comment); await db.commit(); await db.refresh(ticket)
    return {"ticket_id": ticket.id, "status": ticket.status, "updated_at": ticket.updated_at}


@router.post("/tickets/{ticket_id}/drafts", status_code=201)
async def add_draft(ticket_id: UUID, payload: DraftRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("ticket:update", user); visible = await get_visible_ticket(db, user, ticket_id); ticket = await locked_ticket(db, visible.id, user.tenant_id)
    if canonical_role(user.role) == "support_agent" and ticket.assignee_id != user.id: raise HTTPException(403, "Only the assigned engineer can edit the response")
    if ticket.status not in {"in_progress", "changes_requested"}: raise HTTPException(409, "Response drafts can only be edited while work is in progress")
    draft = await create_draft(db, ticket, user, payload.content, "engineer", "engineer_edited", payload.based_on_draft_id, payload.citations)
    record_event(db, ticket, user, "response_draft_created", ticket.status, ticket.status, None, draft.version_number, "internal")
    await db.commit(); await db.refresh(draft); return draft_json(draft)


@router.post("/tickets/{ticket_id}/submit-for-review")
async def submit_for_review(ticket_id: UUID, payload: CommentRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("ticket:update", user); visible = await get_visible_ticket(db, user, ticket_id); ticket = await locked_ticket(db, visible.id, user.tenant_id)
    if canonical_role(user.role) == "support_agent" and ticket.assignee_id != user.id: raise HTTPException(403, "Only the assigned engineer can submit this response")
    draft = await db.get(ResponseDraft, ticket.latest_draft_id) if ticket.latest_draft_id else None
    if not draft or draft.status != "engineer_edited": raise HTTPException(409, "An engineer response draft is required")
    ensure_response_ready(draft)
    draft.status = "submitted_for_review"; transition(db, ticket, user, "pending_review", "response_submitted_for_review", payload.comment, "internal", draft.version_number); ticket.review_required = True
    await db.commit(); await db.refresh(ticket); await db.refresh(draft); return {"ticket_id": ticket.id, "status": ticket.status, "draft": draft_json(draft), "updated_at": ticket.updated_at}


@router.post("/tickets/{ticket_id}/review")
async def review(ticket_id: UUID, payload: ReviewRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("review:manage", user); visible = await get_visible_ticket(db, user, ticket_id); ticket = await locked_ticket(db, visible.id, user.tenant_id)
    draft = await db.get(ResponseDraft, ticket.latest_draft_id) if ticket.latest_draft_id else None
    if not draft or draft.status != "submitted_for_review": raise HTTPException(409, "A submitted response draft is required")
    if payload.action in {"approve", "modify_and_approve"}:
        approved = await approve_draft(db, ticket, user, draft, payload.response_content, payload.review_comment, payload.action == "modify_and_approve")
        if payload.customer_visible_note: ticket.public_status_message = payload.customer_visible_note
        ticket.review_required = False; await db.commit(); await db.refresh(ticket); await db.refresh(approved)
        return {"ticket_id": ticket.id, "status": ticket.status, "final_response": ticket.final_response, "approved_draft": draft_json(approved), "updated_at": ticket.updated_at}
    if payload.action in {"request_changes", "reject"}:
        draft.status = "rejected" if payload.action == "reject" else "changes_requested"; transition(db, ticket, user, "changes_requested", f"review_{payload.action}", payload.review_comment, "internal", draft.version_number); ticket.review_required = False
        db.add(Feedback(ticket_id=ticket.id, reviewer_id=user.id, action="reject", reject_reason=payload.review_comment))
    else:
        draft.status = "rejected"; transition(db, ticket, user, "escalated", "review_escalated", payload.review_comment, "internal", draft.version_number); ticket.public_status_message = payload.customer_visible_note or "Your ticket has been escalated to a specialist."
        db.add(Feedback(ticket_id=ticket.id, reviewer_id=user.id, action="escalate", reject_reason=payload.review_comment))
    await db.commit(); await db.refresh(ticket); return {"ticket_id": ticket.id, "status": ticket.status, "final_response": None, "updated_at": ticket.updated_at}


@router.post("/tickets/{ticket_id}/escalate")
async def escalate(ticket_id: UUID, payload: CommentRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("ticket:escalate", user); visible = await get_visible_ticket(db, user, ticket_id); ticket = await locked_ticket(db, visible.id, user.tenant_id)
    transition(db, ticket, user, "escalated", "ticket_escalated", payload.comment, "internal"); await db.commit(); await db.refresh(ticket)
    return {"ticket_id": ticket.id, "status": ticket.status, "public_status_message": ticket.public_status_message, "updated_at": ticket.updated_at}


@router.post("/tickets/{ticket_id}/reopen")
async def reopen(ticket_id: UUID, payload: CommentRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not (is_customer(user.role) or has_permission(user.role, "ticket:update")): raise HTTPException(403, "Reopen permission required")
    visible = await get_visible_ticket(db, user, ticket_id); ticket = await locked_ticket(db, visible.id, user.tenant_id)
    transition(db, ticket, user, "reopened", "ticket_reopened", payload.comment, "both"); ticket.final_response = None; ticket.final_response_draft_id = None; ticket.approved_at = None; ticket.resolved_at = None
    await db.commit(); await db.refresh(ticket); return {"ticket_id": ticket.id, "status": ticket.status, "updated_at": ticket.updated_at}


@router.get("/departments/{department_id}/engineers")
async def department_engineers(department_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not (has_permission(user.role, "ticket:assign") or canonical_role(user.role) == "support_agent"): raise HTTPException(403, "Department engineer access required")
    rows = (await db.scalars(select(User).join(EngineerDepartment, EngineerDepartment.user_id == User.id).where(User.tenant_id == user.tenant_id, EngineerDepartment.department_id == department_id, User.is_active.is_(True)))).all()
    return [{"id": row.id, "full_name": row.full_name, "email": row.email, "department_id": row.department_id, "is_active": row.is_active} for row in rows]


@router.get("/admin/engineers")
async def admin_engineers(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("user:manage", user); engineers = (await db.scalars(select(User).where(User.tenant_id == user.tenant_id, User.role.in_(["support_agent", "department_engineer"])).order_by(User.full_name))).all(); result = []
    for engineer in engineers:
        active = await db.scalar(select(func.count()).select_from(Ticket).where(Ticket.assignee_id == engineer.id, Ticket.status.notin_(["resolved", "closed"]), Ticket.deleted_at.is_(None))); resolved = await db.scalar(select(func.count()).select_from(Ticket).where(Ticket.assignee_id == engineer.id, Ticket.status.in_(["resolved", "closed"]), Ticket.deleted_at.is_(None))); specs = (await db.scalars(select(EngineerSpecialization.name).where(EngineerSpecialization.user_id == engineer.id))).all()
        result.append({"id": engineer.id, "full_name": engineer.full_name, "email": engineer.email, "department_id": engineer.department_id, "is_active": engineer.is_active, "is_available":engineer.is_available,"max_active_workload":engineer.max_active_workload,"active_tickets": active or 0, "resolved_tickets": resolved or 0, "specializations": list(specs)})
    return result


@router.get("/admin/departments")
async def admin_departments(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("user:manage", user)
    rows=(await db.scalars(select(Department).where(Department.tenant_id==user.tenant_id).order_by(Department.name))).all()
    return [{"id":row.id,"name":row.name,"description":row.description} for row in rows]


@router.post("/admin/engineers", status_code=201)
async def create_engineer(payload: EngineerCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("user:manage", user)
    if await db.scalar(select(User).where(User.email == payload.email)): raise HTTPException(409, "Email already registered")
    department = await db.scalar(select(Department).where(Department.id == payload.department_id, Department.tenant_id == user.tenant_id))
    if not department: raise HTTPException(404, "Department not found")
    engineer = User(email=payload.email.lower(), full_name=payload.full_name.strip(), role="department_engineer", public_role="engineer", hashed_password=hash_password(payload.password), tenant_id=user.tenant_id, department_id=payload.department_id, is_active=True,is_available=payload.is_available,max_active_workload=payload.max_active_workload)
    db.add(engineer); await db.flush(); db.add(EngineerDepartment(user_id=engineer.id, department_id=payload.department_id)); db.add(EngineerProfile(user_id=engineer.id,tenant_id=user.tenant_id,availability_status="available" if payload.is_available else "offline",max_weighted_capacity=float(payload.max_active_workload)))
    for index,name in enumerate(sorted({value.strip() for value in payload.specializations if value.strip()})):
        db.add(EngineerSpecialization(user_id=engineer.id, department_id=payload.department_id, name=name[:120])); db.add(EngineerSkill(tenant_id=user.tenant_id,user_id=engineer.id,department_id=payload.department_id,specialization=name[:120],skill_level="intermediate",is_primary=index==0))
    await db.execute(text("INSERT INTO user_roles(user_id,role_id,tenant_id,department_id) SELECT :uid,id,:tid,:did FROM roles WHERE name='support_agent'"),{"uid":engineer.id,"tid":user.tenant_id,"did":payload.department_id})
    db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="engineer.created",resource_type="user",resource_id=str(engineer.id),metadata_json={"department_id":str(payload.department_id),"specializations":payload.specializations}))
    await db.commit(); await db.refresh(engineer)
    return {"id":engineer.id,"email":engineer.email,"full_name":engineer.full_name,"department_id":engineer.department_id,"is_active":engineer.is_active,"specializations":payload.specializations}


@router.patch("/admin/engineers/{engineer_id}")
async def update_engineer(engineer_id: UUID, payload: EngineerUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require("user:manage", user); engineer=await db.scalar(select(User).where(User.id==engineer_id,User.tenant_id==user.tenant_id,User.role.in_(["support_agent","department_engineer"])).with_for_update())
    if not engineer: raise HTTPException(404,"Engineer not found")
    if payload.full_name is not None: engineer.full_name=payload.full_name.strip()
    if payload.is_active is not None: engineer.is_active=payload.is_active
    if payload.is_available is not None: engineer.is_available=payload.is_available
    if payload.max_active_workload is not None: engineer.max_active_workload=payload.max_active_workload
    profile=await db.get(EngineerProfile,engineer.id)
    if not profile:
        profile=EngineerProfile(user_id=engineer.id,tenant_id=user.tenant_id,availability_status="available" if engineer.is_available else "offline",max_weighted_capacity=float(engineer.max_active_workload));db.add(profile)
    if payload.is_available is not None: profile.availability_status="available" if payload.is_available else "offline"
    if payload.max_active_workload is not None: profile.max_weighted_capacity=float(payload.max_active_workload)
    if payload.department_id is not None:
        department = await db.scalar(select(Department).where(Department.id == payload.department_id, Department.tenant_id == user.tenant_id))
        if not department: raise HTTPException(404,"Department not found")
        engineer.department_id=payload.department_id
        await db.execute(EngineerDepartment.__table__.delete().where(EngineerDepartment.user_id==engineer.id)); db.add(EngineerDepartment(user_id=engineer.id,department_id=payload.department_id))
    if payload.specializations is not None:
        await db.execute(EngineerSpecialization.__table__.delete().where(EngineerSpecialization.user_id==engineer.id))
        await db.execute(EngineerSkill.__table__.delete().where(EngineerSkill.user_id==engineer.id))
        for index,name in enumerate(sorted({value.strip() for value in payload.specializations if value.strip()})):
            db.add(EngineerSpecialization(user_id=engineer.id,department_id=engineer.department_id,name=name[:120]));db.add(EngineerSkill(tenant_id=user.tenant_id,user_id=engineer.id,department_id=engineer.department_id,specialization=name[:120],skill_level="intermediate",is_primary=index==0))
    db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="engineer.updated",resource_type="user",resource_id=str(engineer.id),metadata_json={key:(str(value) if key=="department_id" and value else value) for key,value in payload.model_dump(exclude_none=True).items()}))
    await db.commit(); await db.refresh(engineer)
    return {"id":engineer.id,"email":engineer.email,"full_name":engineer.full_name,"department_id":engineer.department_id,"is_active":engineer.is_active,"specializations":payload.specializations}


@router.get("/workloads/engineers")
async def engineer_workloads(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    role=canonical_role(user.role)
    if role not in {"team_lead","system_admin"}: raise HTTPException(403,"Workload access required")
    query=select(User).where(User.tenant_id==user.tenant_id,User.role.in_(["support_agent","department_engineer"]))
    if role=="team_lead": query=query.where(User.department_id==user.department_id)
    engineers=(await db.scalars(query.order_by(User.full_name))).all(); output=[]
    active_states=["assigned","in_progress","pending_review","changes_requested","reopened","escalated"]
    for engineer in engineers:
        rows=(await db.execute(select(Ticket.status,func.count()).where(Ticket.assignee_id==engineer.id,Ticket.deleted_at.is_(None)).group_by(Ticket.status))).all(); counts={status:int(count) for status,count in rows}; active=sum(counts.get(state,0) for state in active_states)
        avg_seconds=await db.scalar(select(func.avg(func.extract("epoch",Ticket.resolved_at-Ticket.created_at))).where(Ticket.assignee_id==engineer.id,Ticket.resolved_at.is_not(None)))
        specs=list((await db.scalars(select(EngineerSpecialization.name).where(EngineerSpecialization.user_id==engineer.id))).all())
        department=await db.get(Department,engineer.department_id) if engineer.department_id else None
        output.append({"id":engineer.id,"name":engineer.full_name,"department_id":engineer.department_id,"department":department.name if department else None,"specializations":specs,"is_active":engineer.is_active,"is_available":engineer.is_available,"capacity":engineer.max_active_workload,"active_workload":active,"capacity_percent":round(active/engineer.max_active_workload*100,1),"assigned":counts.get("assigned",0),"in_progress":counts.get("in_progress",0),"under_review":counts.get("pending_review",0),"returned":counts.get("changes_requested",0),"escalated":counts.get("escalated",0),"resolved":counts.get("resolved",0),"average_resolution_hours":round(float(avg_seconds)/3600,2) if avg_seconds is not None else None})
    return output


@router.get("/admin/departments/{department_id}/confidence-policy")
async def get_confidence_policy(department_id:UUID,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    require("department:manage",user); department=await db.scalar(select(Department).where(Department.id==department_id,Department.tenant_id==user.tenant_id))
    if not department: raise HTTPException(404,"Department not found")
    policy=await db.scalar(select(DepartmentConfidencePolicy).where(DepartmentConfidencePolicy.tenant_id==user.tenant_id,DepartmentConfidencePolicy.department_id==department_id).order_by(DepartmentConfidencePolicy.version.desc()).limit(1))
    return {"department_id":department_id,"department":department.name,"low_threshold":policy.low_threshold if policy else .55,"high_threshold":policy.high_threshold if policy else .80,"version":policy.version if policy else 0,"effective_at":policy.effective_at if policy else None,"reason":policy.reason if policy else "Global defaults"}


@router.post("/admin/departments/{department_id}/confidence-policy",status_code=201)
async def set_confidence_policy(department_id:UUID,payload:ConfidencePolicyRequest,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    require("department:manage",user)
    if payload.low_threshold>payload.high_threshold: raise HTTPException(422,"Low threshold cannot exceed high threshold")
    department=await db.scalar(select(Department).where(Department.id==department_id,Department.tenant_id==user.tenant_id).with_for_update())
    if not department: raise HTTPException(404,"Department not found")
    version=int(await db.scalar(select(func.max(DepartmentConfidencePolicy.version)).where(DepartmentConfidencePolicy.tenant_id==user.tenant_id,DepartmentConfidencePolicy.department_id==department_id)) or 0)+1; now=datetime.now(timezone.utc)
    policy=DepartmentConfidencePolicy(tenant_id=user.tenant_id,department_id=department_id,low_threshold=payload.low_threshold,high_threshold=payload.high_threshold,version=version,effective_at=now,updated_by=user.id,reason=payload.reason)
    db.add(policy);db.add(AuditLog(tenant_id=user.tenant_id,user_id=user.id,action="department.confidence_policy_updated",resource_type="department",resource_id=str(department_id),metadata_json={"version":version,"low_threshold":payload.low_threshold,"high_threshold":payload.high_threshold}));await db.commit();await db.refresh(policy)
    return {"department_id":department_id,"low_threshold":policy.low_threshold,"high_threshold":policy.high_threshold,"version":policy.version,"effective_at":policy.effective_at,"reason":policy.reason}
