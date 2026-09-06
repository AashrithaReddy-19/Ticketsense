"""TicketSense V2 OCR/multimodal diagnostic benchmark lab API. Ground-truth
images here are always curated/synthetic — never real customer attachments —
and a benchmark run reports the real, live availability of the engine it
targeted rather than a fabricated score. See app.services.ocr for the engine
registry and app.services.ocr.benchmark for the run logic."""
import base64
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.ocr_benchmark import OCR_ENGINES, OcrBenchmarkCase, OcrBenchmarkDataset, OcrBenchmarkResult, OcrBenchmarkRun
from app.models.platform import AuditLog
from app.models.user import User
from app.services.feature_flags import require_feature
from app.services.ocr.benchmark import OcrBenchmarkError, add_case, run_benchmark
from app.services.ocr.engines import available_engines

router = APIRouter(prefix="/api/v2/ocr-benchmark", tags=["v2-ocr-benchmark"])


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_flag(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "multimodal_analysis", user, permissions)


def dataset_json(row: OcrBenchmarkDataset, case_count: int = 0) -> dict:
    return {"id": row.id, "key": row.key, "name": row.name, "description": row.description, "case_count": case_count, "created_at": row.created_at}


def case_json(row: OcrBenchmarkCase) -> dict:
    return {"id": row.id, "dataset_id": row.dataset_id, "image_sha256": row.image_sha256, "ground_truth_text": row.ground_truth_text, "source_label": row.source_label, "tags": row.tags, "created_at": row.created_at}


def run_json(row: OcrBenchmarkRun) -> dict:
    return {
        "id": row.id, "dataset_id": row.dataset_id, "engine": row.engine, "status": row.status,
        "unavailable_reason": row.unavailable_reason, "row_count_considered": row.row_count_considered,
        "mean_character_error_rate": float(row.mean_character_error_rate) if row.mean_character_error_rate is not None else None,
        "mean_word_error_rate": float(row.mean_word_error_rate) if row.mean_word_error_rate is not None else None,
        "mean_latency_ms": float(row.mean_latency_ms) if row.mean_latency_ms is not None else None,
        "environment_info": row.environment_info, "started_at": row.started_at, "completed_at": row.completed_at,
        "created_at": row.created_at,
    }


@router.get("/engines")
async def list_engines(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "ocr_benchmark:read")
    await require_flag(db, user)
    return {"engines": available_engines()}


class DatasetCreate(BaseModel):
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)


@router.post("/datasets", status_code=201)
async def create_dataset(payload: DatasetCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "ocr_benchmark:manage")
    await require_flag(db, user)
    existing = await db.scalar(select(OcrBenchmarkDataset).where(OcrBenchmarkDataset.tenant_id == user.tenant_id, OcrBenchmarkDataset.key == payload.key))
    if existing:
        raise HTTPException(409, "A dataset with this key already exists")
    dataset = OcrBenchmarkDataset(tenant_id=user.tenant_id, key=payload.key, name=payload.name, description=payload.description, created_by=user.id)
    db.add(dataset)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.ocr_benchmark.dataset_created", resource_type="ocr_benchmark_dataset", resource_id=None, metadata_json={"key": payload.key}))
    await db.commit(); await db.refresh(dataset)
    return dataset_json(dataset)


@router.get("/datasets")
async def list_datasets(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "ocr_benchmark:read")
    await require_flag(db, user)
    rows = (await db.scalars(select(OcrBenchmarkDataset).where(OcrBenchmarkDataset.tenant_id == user.tenant_id).order_by(OcrBenchmarkDataset.created_at.desc()))).all()
    counts = {row[0]: row[1] for row in (await db.execute(
        select(OcrBenchmarkCase.dataset_id, func.count()).where(OcrBenchmarkCase.tenant_id == user.tenant_id).group_by(OcrBenchmarkCase.dataset_id)
    )).all()}
    return {"items": [dataset_json(r, counts.get(r.id, 0)) for r in rows]}


class CaseCreate(BaseModel):
    image_base64: str = Field(min_length=1)
    ground_truth_text: str = Field(min_length=1, max_length=20_000)
    tags: list[str] = Field(default_factory=list)


@router.post("/datasets/{dataset_id}/cases", status_code=201)
async def create_case(dataset_id: UUID, payload: CaseCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "ocr_benchmark:manage")
    await require_flag(db, user)
    dataset = await db.scalar(select(OcrBenchmarkDataset).where(OcrBenchmarkDataset.id == dataset_id, OcrBenchmarkDataset.tenant_id == user.tenant_id))
    if not dataset:
        raise HTTPException(404, "Dataset not found")
    try:
        image_bytes = base64.b64decode(payload.image_base64, validate=True)
    except Exception:
        raise HTTPException(422, "image_base64 is not valid base64 data")
    if len(image_bytes) > 5_000_000:
        raise HTTPException(422, "Image exceeds the 5MB benchmark case limit")
    case = await add_case(db, user.tenant_id, dataset_id, user.id, image_bytes, payload.ground_truth_text, payload.tags)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.ocr_benchmark.case_added", resource_type="ocr_benchmark_case", resource_id=str(case.id), metadata_json={"dataset_id": str(dataset_id)}))
    await db.commit(); await db.refresh(case)
    return case_json(case)


@router.get("/datasets/{dataset_id}/cases")
async def list_cases(dataset_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "ocr_benchmark:read")
    await require_flag(db, user)
    rows = (await db.scalars(select(OcrBenchmarkCase).where(OcrBenchmarkCase.dataset_id == dataset_id, OcrBenchmarkCase.tenant_id == user.tenant_id).order_by(OcrBenchmarkCase.created_at))).all()
    return {"items": [case_json(r) for r in rows]}


class RunCreate(BaseModel):
    dataset_id: UUID
    engine: str = Field(pattern="^(" + "|".join(OCR_ENGINES) + ")$")


@router.post("/runs", status_code=201)
async def create_run(payload: RunCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "ocr_benchmark:manage")
    await require_flag(db, user)
    dataset = await db.scalar(select(OcrBenchmarkDataset).where(OcrBenchmarkDataset.id == payload.dataset_id, OcrBenchmarkDataset.tenant_id == user.tenant_id))
    if not dataset:
        raise HTTPException(404, "Dataset not found")
    try:
        run = await run_benchmark(db, user.tenant_id, payload.dataset_id, payload.engine, user.id)
    except OcrBenchmarkError as exc:
        raise HTTPException(422, str(exc))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.ocr_benchmark.run_created", resource_type="ocr_benchmark_run", resource_id=str(run.id), metadata_json={"engine": run.engine, "status": run.status}))
    await db.commit(); await db.refresh(run)
    return run_json(run)


@router.get("/runs")
async def list_runs(dataset_id: UUID | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "ocr_benchmark:read")
    await require_flag(db, user)
    query = select(OcrBenchmarkRun).where(OcrBenchmarkRun.tenant_id == user.tenant_id)
    if dataset_id:
        query = query.where(OcrBenchmarkRun.dataset_id == dataset_id)
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = (await db.scalars(query.order_by(OcrBenchmarkRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [run_json(r) for r in rows], "page": page, "page_size": page_size, "total": total}


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "ocr_benchmark:read")
    await require_flag(db, user)
    run = await db.scalar(select(OcrBenchmarkRun).where(OcrBenchmarkRun.id == run_id, OcrBenchmarkRun.tenant_id == user.tenant_id))
    if not run:
        raise HTTPException(404, "Run not found")
    results = (await db.scalars(select(OcrBenchmarkResult).where(OcrBenchmarkResult.run_id == run_id))).all()
    payload = run_json(run)
    payload["results"] = [
        {"id": r.id, "case_id": r.case_id, "extracted_text": r.extracted_text, "character_error_rate": float(r.character_error_rate), "word_error_rate": float(r.word_error_rate), "latency_ms": float(r.latency_ms)}
        for r in results
    ]
    return payload
