"""Section 19: safe action framework APIs."""
import asyncio
from datetime import datetime, timezone
from time import monotonic
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.platform import AuditLog
from app.models.safe_action import SafeActionApproval, SafeActionDefinition, SafeActionExecution, SafeActionResult
from app.models.user import User
from app.services.safe_actions import REGISTRY, ActionContext, parse_params, run_action
from app.services.ticket_visibility import get_visible_ticket

router = APIRouter(prefix="/api/safe-actions", tags=["safe-actions"])


class ActionRequest(BaseModel):
    parameters: dict = Field(default_factory=dict)
    ticket_id: UUID | None = None
    confirm: bool = False
    customer_consent: bool = False


def definition_json(d: SafeActionDefinition) -> dict:
    return {"action_key": d.action_key, "display_name": d.display_name, "description": d.description, "category": d.category,
            "risk_level": d.risk_level, "required_capability": d.required_capability, "parameter_schema": d.parameter_schema,
            "requires_confirmation": d.requires_confirmation, "requires_customer_consent": d.requires_customer_consent,
            "enabled": d.enabled, "connector": d.connector, "timeout_seconds": d.timeout_seconds,
            "supports_dry_run": d.supports_dry_run, "supports_rollback": d.supports_rollback}


def execution_json(e: SafeActionExecution, result: SafeActionResult | None = None) -> dict:
    payload = {"id": e.id, "action_key": e.action_key, "ticket_id": e.ticket_id, "department_id": e.department_id,
               "requested_by": e.requested_by, "mode": e.mode, "status": e.status, "requires_approval": e.requires_approval,
               "error_summary": e.error_summary, "started_at": e.started_at, "completed_at": e.completed_at,
               "duration_ms": e.duration_ms, "created_at": e.created_at}
    if result:
        payload["result"] = {"summary": result.result_summary, "data": result.result_data, "evidence": result.evidence,
                             "sandbox": result.sandbox, "rollback_available": result.rollback_available, "rolled_back": result.rolled_back}
    return payload


async def get_definition(db: AsyncSession, action_key: str) -> SafeActionDefinition:
    definition = await db.scalar(select(SafeActionDefinition).where(SafeActionDefinition.action_key == action_key))
    if not definition or action_key not in REGISTRY:
        raise HTTPException(404, "Unknown safe action")
    return definition


@router.get("")
async def list_actions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(SafeActionDefinition).order_by(SafeActionDefinition.category, SafeActionDefinition.display_name))).all()
    visible = [d for d in rows if await user_has_permission(db, user, d.required_capability)]
    return [definition_json(d) for d in visible]


@router.get("/{action_key}")
async def get_action(action_key: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    definition = await get_definition(db, action_key)
    if not await user_has_permission(db, user, definition.required_capability):
        raise HTTPException(403, f"Permission required: {definition.required_capability}")
    return definition_json(definition)


async def _resolve_scope(db: AsyncSession, user: User, payload: ActionRequest) -> UUID | None:
    """Returns the department_id this execution is scoped to, enforcing that an
    Engineer may only act on a ticket they are actually assigned to."""
    if payload.ticket_id is None:
        return None
    ticket = await get_visible_ticket(db, user, payload.ticket_id)
    if user.public_role == "engineer" and ticket.assignee_id != user.id:
        raise HTTPException(403, "Only the assigned Engineer can act on this ticket")
    return ticket.department_id


async def _execute_and_record(db: AsyncSession, execution: SafeActionExecution, definition: SafeActionDefinition, params) -> SafeActionExecution:
    ctx = ActionContext(tenant_id=execution.tenant_id, user_id=execution.requested_by, department_id=execution.department_id)
    execution.status = "running"
    execution.started_at = datetime.now(timezone.utc)
    start = monotonic()
    try:
        result = await asyncio.wait_for(run_action(db, execution.action_key, ctx, params), timeout=definition.timeout_seconds)
    except asyncio.TimeoutError:
        execution.status = "timed_out"
        execution.error_summary = f"Action did not complete within {definition.timeout_seconds}s"
    except ValueError as exc:
        execution.status = "failed"
        execution.error_summary = str(exc)
    except Exception:
        execution.status = "failed"
        execution.error_summary = "An internal error occurred while executing this action"
    else:
        execution.status = "succeeded"
        db.add(SafeActionResult(execution_id=execution.id, result_summary=result.summary, result_data=result.data,
                                 evidence=result.evidence, sandbox=result.sandbox))
    execution.completed_at = datetime.now(timezone.utc)
    execution.duration_ms = round((monotonic() - start) * 1000)
    return execution


@router.post("/{action_key}/preview")
async def preview_action(action_key: str, payload: ActionRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    definition = await get_definition(db, action_key)
    if not await user_has_permission(db, user, definition.required_capability):
        raise HTTPException(403, f"Permission required: {definition.required_capability}")
    if not definition.enabled:
        raise HTTPException(403, "This action is currently disabled")
    if not definition.supports_dry_run:
        raise HTTPException(409, "This action does not support preview")
    try:
        params = parse_params(action_key, payload.parameters)
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid parameters: {exc.errors()[0]['msg'] if exc.errors() else 'validation failed'}")
    department_id = await _resolve_scope(db, user, payload)
    return {"action_key": action_key, "mode": "preview", "would_do": definition.description,
            "would_not_do": "No data is created, modified, or sent — this is a preview only.",
            "parameters": params.model_dump(mode="json"), "risk_level": definition.risk_level,
            "requires_confirmation": definition.requires_confirmation, "requires_customer_consent": definition.requires_customer_consent,
            "department_id": department_id}


@router.post("/{action_key}/execute", status_code=201)
async def execute_action(action_key: str, payload: ActionRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    definition = await get_definition(db, action_key)
    if not await user_has_permission(db, user, definition.required_capability):
        raise HTTPException(403, f"Permission required: {definition.required_capability}")
    if not definition.enabled:
        raise HTTPException(403, "This action is currently disabled")

    existing = await db.scalar(select(SafeActionExecution).where(
        SafeActionExecution.tenant_id == user.tenant_id, SafeActionExecution.action_key == action_key,
        SafeActionExecution.idempotency_key == idempotency_key))
    if existing:
        result = await db.scalar(select(SafeActionResult).where(SafeActionResult.execution_id == existing.id))
        return execution_json(existing, result)

    if definition.requires_confirmation and not payload.confirm:
        raise HTTPException(422, "This action requires explicit confirmation (confirm=true)")
    if definition.requires_customer_consent and not payload.customer_consent:
        raise HTTPException(422, "This action requires customer consent (customer_consent=true)")
    try:
        params = parse_params(action_key, payload.parameters)
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid parameters: {exc.errors()[0]['msg'] if exc.errors() else 'validation failed'}")

    department_id = await _resolve_scope(db, user, payload)
    requires_approval = definition.risk_level == "high"
    execution = SafeActionExecution(tenant_id=user.tenant_id, action_key=action_key, ticket_id=payload.ticket_id,
                                     department_id=department_id, requested_by=user.id, parameters=payload.parameters,
                                     mode="execute", status="pending_approval" if requires_approval else "pending",
                                     requires_approval=requires_approval, idempotency_key=idempotency_key)
    db.add(execution)
    await db.flush()
    if requires_approval:
        db.add(SafeActionApproval(execution_id=execution.id, requested_by=user.id))
        db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="safe_action.approval_requested", resource_type="safe_action_execution",
                         resource_id=str(execution.id), metadata_json={"action_key": action_key}))
        await db.commit()
        await db.refresh(execution)
        return execution_json(execution)

    execution = await _execute_and_record(db, execution, definition, params)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="safe_action.executed", resource_type="safe_action_execution",
                     resource_id=str(execution.id), metadata_json={"action_key": action_key, "status": execution.status}))
    await db.commit()
    await db.refresh(execution)
    result = await db.scalar(select(SafeActionResult).where(SafeActionResult.execution_id == execution.id))
    return execution_json(execution, result)


@router.post("/executions/{execution_id}/approve")
async def approve_execution(execution_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await user_has_permission(db, user, "safe_action:execute"):
        raise HTTPException(403, "Permission required: safe_action:execute")
    execution = await db.scalar(select(SafeActionExecution).where(SafeActionExecution.id == execution_id, SafeActionExecution.tenant_id == user.tenant_id).with_for_update())
    if not execution:
        raise HTTPException(404, "Execution not found")
    if execution.status != "pending_approval":
        raise HTTPException(409, "Only a pending-approval execution can be approved")
    if execution.requested_by == user.id:
        raise HTTPException(403, "The requester cannot approve their own high-risk action")
    approval = await db.scalar(select(SafeActionApproval).where(SafeActionApproval.execution_id == execution.id))
    approval.decision = "approved"
    approval.decided_by = user.id
    approval.decided_at = datetime.now(timezone.utc)
    definition = await get_definition(db, execution.action_key)
    params = parse_params(execution.action_key, execution.parameters)
    execution = await _execute_and_record(db, execution, definition, params)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="safe_action.approved_and_executed", resource_type="safe_action_execution",
                     resource_id=str(execution.id), metadata_json={"action_key": execution.action_key, "status": execution.status}))
    await db.commit()
    await db.refresh(execution)
    result = await db.scalar(select(SafeActionResult).where(SafeActionResult.execution_id == execution.id))
    return execution_json(execution, result)


@router.post("/executions/{execution_id}/reject")
async def reject_execution(execution_id: UUID, reason: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await user_has_permission(db, user, "safe_action:execute"):
        raise HTTPException(403, "Permission required: safe_action:execute")
    execution = await db.scalar(select(SafeActionExecution).where(SafeActionExecution.id == execution_id, SafeActionExecution.tenant_id == user.tenant_id).with_for_update())
    if not execution:
        raise HTTPException(404, "Execution not found")
    if execution.status != "pending_approval":
        raise HTTPException(409, "Only a pending-approval execution can be rejected")
    approval = await db.scalar(select(SafeActionApproval).where(SafeActionApproval.execution_id == execution.id))
    approval.decision = "rejected"
    approval.decided_by = user.id
    approval.decided_at = datetime.now(timezone.utc)
    approval.reason = reason or None
    execution.status = "rejected"
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="safe_action.rejected", resource_type="safe_action_execution",
                     resource_id=str(execution.id), metadata_json={"action_key": execution.action_key, "reason": reason}))
    await db.commit()
    await db.refresh(execution)
    return execution_json(execution)


@router.get("/executions")
async def list_executions(ticket_id: UUID | None = None, action_key: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await user_has_permission(db, user, "safe_action:execute"):
        raise HTTPException(403, "Permission required: safe_action:execute")
    query = select(SafeActionExecution).where(SafeActionExecution.tenant_id == user.tenant_id)
    if ticket_id:
        query = query.where(SafeActionExecution.ticket_id == ticket_id)
    if action_key:
        query = query.where(SafeActionExecution.action_key == action_key)
    rows = (await db.scalars(query.order_by(SafeActionExecution.created_at.desc()).limit(100))).all()
    results = {r.execution_id: r for r in (await db.scalars(select(SafeActionResult).where(SafeActionResult.execution_id.in_([row.id for row in rows])))).all()}
    return [execution_json(row, results.get(row.id)) for row in rows]


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await user_has_permission(db, user, "safe_action:execute"):
        raise HTTPException(403, "Permission required: safe_action:execute")
    execution = await db.scalar(select(SafeActionExecution).where(SafeActionExecution.id == execution_id, SafeActionExecution.tenant_id == user.tenant_id))
    if not execution:
        raise HTTPException(404, "Execution not found")
    result = await db.scalar(select(SafeActionResult).where(SafeActionResult.execution_id == execution.id))
    return execution_json(execution, result)


@router.get("/executions/{execution_id}/result")
async def get_execution_result(execution_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await user_has_permission(db, user, "safe_action:execute"):
        raise HTTPException(403, "Permission required: safe_action:execute")
    execution = await db.scalar(select(SafeActionExecution).where(SafeActionExecution.id == execution_id, SafeActionExecution.tenant_id == user.tenant_id))
    if not execution:
        raise HTTPException(404, "Execution not found")
    result = await db.scalar(select(SafeActionResult).where(SafeActionResult.execution_id == execution.id))
    if not result:
        raise HTTPException(404, "No result yet for this execution")
    return {"summary": result.result_summary, "data": result.result_data, "evidence": result.evidence,
            "sandbox": result.sandbox, "rollback_available": result.rollback_available, "rolled_back": result.rolled_back}
