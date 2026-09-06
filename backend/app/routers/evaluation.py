"""TicketSense V2 Evaluation Lab: reproducible classification evaluation runs.

Gated behind the ``evaluation_lab`` feature flag, same as the dataset
registry it reads from. Every number returned here is computed by
``app.services.evaluation.metrics`` from real predictions against real
labelled rows — there is no sample/demo metric path.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.dataset import Dataset, DatasetRow, DatasetVersion
from app.models.evaluation import EvaluationArtifact, EvaluationExample, EvaluationMetric, EvaluationRun
from app.models.platform import AuditLog
from app.models.user import User
from app.services.evaluation.runner import EvaluationRunError, run_classification_evaluation
from app.services.feature_flags import require_feature

router = APIRouter(prefix="/api/v2/evaluation", tags=["v2-evaluation"])


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_lab_enabled(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "evaluation_lab", user, permissions)


class RunCreate(BaseModel):
    dataset_version_id: UUID
    target: str = Field(pattern="^(department|priority|sentiment)$")
    notes: str | None = Field(default=None, max_length=2_000)


def run_json(run: EvaluationRun) -> dict:
    return {
        "id": run.id, "dataset_version_id": run.dataset_version_id, "target": run.target,
        "model_artifact_path": run.model_artifact_path, "model_artifact_hash": run.model_artifact_hash,
        "git_commit": run.git_commit, "environment_info": run.environment_info,
        "config_snapshot": run.config_snapshot, "split_used": run.split_used, "status": run.status,
        "row_count_considered": run.row_count_considered, "row_count_excluded": run.row_count_excluded,
        "exclusion_reasons": run.exclusion_reasons, "started_at": run.started_at, "completed_at": run.completed_at,
        "notes": run.notes, "created_at": run.created_at,
    }


@router.post("/runs", status_code=201)
async def create_run(payload: RunCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "evaluation:manage")
    await require_lab_enabled(db, user)
    version = await db.scalar(
        select(DatasetVersion).join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(DatasetVersion.id == payload.dataset_version_id, Dataset.tenant_id == user.tenant_id)
    )
    if not version:
        raise HTTPException(404, "Dataset version not found")
    try:
        run = await run_classification_evaluation(db, user.tenant_id, payload.dataset_version_id, payload.target, user.id, payload.notes)
    except EvaluationRunError as exc:
        raise HTTPException(422, str(exc))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.evaluation.run_created", resource_type="evaluation_run", resource_id=str(run.id), metadata_json={"target": run.target, "status": run.status, "row_count_considered": run.row_count_considered}))
    await db.commit(); await db.refresh(run)
    return run_json(run)


@router.get("/runs")
async def list_runs(target: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "evaluation:read")
    await require_lab_enabled(db, user)
    query = select(EvaluationRun).where(EvaluationRun.tenant_id == user.tenant_id)
    if target:
        query = query.where(EvaluationRun.target == target)
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = (await db.scalars(query.order_by(EvaluationRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [run_json(row) for row in rows], "page": page, "page_size": page_size, "total": total}


async def _get_owned_run(db: AsyncSession, user: User, run_id: UUID) -> EvaluationRun:
    run = await db.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.tenant_id == user.tenant_id))
    if not run:
        raise HTTPException(404, "Evaluation run not found")
    return run


@router.get("/runs/{run_id}")
async def run_detail(run_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "evaluation:read")
    await require_lab_enabled(db, user)
    run = await _get_owned_run(db, user, run_id)
    metric_rows = (await db.scalars(select(EvaluationMetric).where(EvaluationMetric.run_id == run_id))).all()
    overall = {row.metric_name: float(row.metric_value) for row in metric_rows if row.scope == "overall"}
    per_class: dict[str, dict] = {}
    for row in metric_rows:
        if row.scope == "per_class":
            per_class.setdefault(row.class_label, {"support": row.support})[row.metric_name] = float(row.metric_value)
    artifact = await db.scalar(select(EvaluationArtifact).where(EvaluationArtifact.run_id == run_id, EvaluationArtifact.artifact_type == "confusion_matrix"))
    return {**run_json(run), "overall_metrics": overall, "per_class_metrics": per_class, "confusion_matrix": artifact.content if artifact else None}


@router.get("/runs/{run_id}/examples")
async def run_examples(run_id: UUID, correct: bool | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "evaluation:read")
    await require_lab_enabled(db, user)
    await _get_owned_run(db, user, run_id)
    query = select(EvaluationExample, DatasetRow.redacted_text).join(DatasetRow, DatasetRow.id == EvaluationExample.dataset_row_id).where(EvaluationExample.run_id == run_id)
    if correct is not None:
        query = query.where(EvaluationExample.correct.is_(correct))
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    pairs = (await db.execute(query.order_by(EvaluationExample.id).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [{
        "id": row.id, "dataset_row_id": row.dataset_row_id, "true_label": row.true_label,
        "predicted_label": row.predicted_label, "correct": row.correct, "top_3_hit": row.top_3_hit,
        "predicted_confidence": float(row.predicted_confidence) if row.predicted_confidence is not None else None,
        "redacted_text": redacted_text,
    } for row, redacted_text in pairs], "page": page, "page_size": page_size, "total": total}


@router.get("/runs/{run_id}/export")
async def export_run(run_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "evaluation:read")
    await require_lab_enabled(db, user)
    run = await _get_owned_run(db, user, run_id)
    metric_rows = (await db.scalars(select(EvaluationMetric).where(EvaluationMetric.run_id == run_id))).all()
    example_rows = (await db.scalars(select(EvaluationExample).where(EvaluationExample.run_id == run_id))).all()
    artifact = await db.scalar(select(EvaluationArtifact).where(EvaluationArtifact.run_id == run_id, EvaluationArtifact.artifact_type == "confusion_matrix"))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.evaluation.run_exported", resource_type="evaluation_run", resource_id=str(run_id), metadata_json={}))
    await db.commit()
    return {
        "run": run_json(run),
        "metrics": [{"scope": m.scope, "class_label": m.class_label, "metric_name": m.metric_name, "metric_value": float(m.metric_value), "support": m.support} for m in metric_rows],
        "examples": [{"true_label": e.true_label, "predicted_label": e.predicted_label, "correct": e.correct, "top_3_hit": e.top_3_hit} for e in example_rows],
        "confusion_matrix": artifact.content if artifact else None,
    }
