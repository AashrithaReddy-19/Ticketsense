"""TicketSense V2 dataset registry: import, versioning, quality reports, revert.

Gated behind the ``evaluation_lab`` feature flag (Phase 1 governance) — the
registry exists to feed the Evaluation Lab (a later phase); until that flag
is enabled for a tenant, these endpoints report the feature as unavailable
rather than silently accepting data nobody can evaluate against yet.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.dataset import Dataset, DatasetImportBatch, DatasetRow, DatasetVersion
from app.models.department import Department
from app.models.platform import AuditLog
from app.models.user import User
from app.services.evaluation import ingestion
from app.services.feature_flags import require_feature

router = APIRouter(prefix="/api/v2/datasets", tags=["v2-datasets"])


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_lab_enabled(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "evaluation_lab", user, permissions)


class DatasetCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,99}$")
    name: str = Field(min_length=3, max_length=200)
    kind: str = Field(pattern="^(ticket_labels|retrieval_judgments)$")
    description: str = Field(min_length=5, max_length=2_000)
    license_notes: str = Field(default="", max_length=2_000)


def dataset_json(row: Dataset) -> dict:
    return {"id": row.id, "key": row.key, "name": row.name, "kind": row.kind,
            "description": row.description, "license_notes": row.license_notes, "created_at": row.created_at}


def version_json(row: DatasetVersion) -> dict:
    return {"id": row.id, "dataset_id": row.dataset_id, "version_number": row.version_number,
            "content_hash": row.content_hash, "row_count": row.row_count,
            "label_distribution": row.label_distribution, "missing_data_stats": row.missing_data_stats,
            "duplicate_rate": float(row.duplicate_rate), "corruption_rate": float(row.corruption_rate),
            "near_duplicate_cross_split_count": row.near_duplicate_cross_split_count,
            "near_duplicate_check_skipped": row.near_duplicate_check_skipped,
            "split_ratio": row.split_ratio, "split_seed": row.split_seed, "status": row.status,
            "provenance": row.provenance, "created_at": row.created_at}


@router.post("", status_code=201)
async def create_dataset(payload: DatasetCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "dataset:manage")
    await require_lab_enabled(db, user)
    if await db.scalar(select(Dataset.id).where(Dataset.tenant_id == user.tenant_id, Dataset.key == payload.key)):
        raise HTTPException(409, "Dataset key already exists for this tenant")
    dataset = Dataset(tenant_id=user.tenant_id, created_by=user.id, **payload.model_dump())
    db.add(dataset)
    await db.flush()
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.dataset.created", resource_type="dataset", resource_id=str(dataset.id), metadata_json={"key": dataset.key, "kind": dataset.kind}))
    await db.commit(); await db.refresh(dataset)
    return dataset_json(dataset)


@router.get("")
async def list_datasets(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "dataset:read")
    await require_lab_enabled(db, user)
    total = int(await db.scalar(select(func.count()).select_from(Dataset).where(Dataset.tenant_id == user.tenant_id)) or 0)
    rows = (await db.scalars(select(Dataset).where(Dataset.tenant_id == user.tenant_id).order_by(Dataset.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [dataset_json(row) for row in rows], "page": page, "page_size": page_size, "total": total}


@router.post("/{dataset_id}/import", status_code=201)
async def import_dataset(
    dataset_id: UUID,
    file: UploadFile = File(...),
    source_format: str = Form(...),
    department_id: UUID | None = Form(None),
    split_seed: str = Form("v1"),
    train_ratio: float = Form(0.7),
    validation_ratio: float = Form(0.15),
    test_ratio: float = Form(0.15),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require(db, user, "dataset:manage")
    await require_lab_enabled(db, user)
    if source_format not in ("csv", "json", "jsonl"):
        raise HTTPException(422, "source_format must be csv, json or jsonl")
    ratio_sum = round(train_ratio + validation_ratio + test_ratio, 4)
    if ratio_sum != 1.0:
        raise HTTPException(422, f"Split ratios must sum to 1.0, got {ratio_sum}")
    dataset = await db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.tenant_id == user.tenant_id))
    if not dataset:
        raise HTTPException(404, "Dataset not found")
    if department_id and not await db.scalar(select(Department.id).where(Department.id == department_id, Department.tenant_id == user.tenant_id)):
        raise HTTPException(422, "Department is outside this tenant")

    raw_bytes = await file.read()
    if len(raw_bytes) > settings_max_bytes():
        raise HTTPException(413, "Dataset file exceeds the configured size limit")
    try:
        records = ingestion.parse_records(raw_bytes, source_format)
    except (ValueError, ingestion.DatasetValidationError) as exc:
        raise HTTPException(422, f"Could not parse dataset file: {exc}")
    if len(records) > settings_max_rows():
        raise HTTPException(413, f"Dataset has {len(records)} rows, exceeding the configured limit")
    if not records:
        raise HTTPException(422, "Dataset file contains no records")

    processed, rejected = ingestion.validate_and_process(records, dataset.kind)
    if not processed:
        raise HTTPException(422, "No rows passed schema validation; nothing was imported")

    ingestion.assign_leakage_safe_splits(processed, (train_ratio, validation_ratio, test_ratio), split_seed)
    near_dup_count, near_dup_skipped = ingestion.detect_cross_split_near_duplicates(processed)
    report = ingestion.build_quality_report(processed, rejected, near_dup_count, near_dup_skipped)
    content_hash = ingestion.dataset_version_content_hash(processed)

    next_version = int(await db.scalar(select(func.coalesce(func.max(DatasetVersion.version_number), 0)).where(DatasetVersion.dataset_id == dataset.id)) or 0) + 1
    version = DatasetVersion(
        dataset_id=dataset.id, version_number=next_version, content_hash=content_hash,
        row_count=len(processed), label_distribution=report["label_distribution"],
        missing_data_stats=report["missing_data_stats"], duplicate_rate=report["duplicate_rate"],
        corruption_rate=report["corruption_rate"], near_duplicate_cross_split_count=near_dup_count,
        near_duplicate_check_skipped=near_dup_skipped,
        split_ratio={"train": train_ratio, "validation": validation_ratio, "test": test_ratio},
        split_seed=split_seed, status="ready",
        provenance={"source_filename": file.filename, "uploaded_by": str(user.id), "license_notes": dataset.license_notes, "language_summary": report["language_summary"]},
        created_by=user.id,
    )
    db.add(version)
    await db.flush()
    batch = DatasetImportBatch(
        dataset_version_id=version.id, source_filename=file.filename or "upload", source_format=source_format,
        raw_row_count=report["raw_row_count"], accepted_row_count=report["accepted_row_count"],
        rejected_row_count=report["rejected_row_count"], rejection_reasons=report["rejection_reasons"],
        created_by=user.id,
    )
    db.add(batch)
    await db.flush()
    rows_by_index: dict[int, DatasetRow] = {}
    for row in processed:
        orm_row = DatasetRow(
            dataset_version_id=version.id, import_batch_id=batch.id, tenant_id=user.tenant_id,
            department_id=department_id, row_index=row.row_index, group_key=row.group_key,
            redacted_text=row.redacted_text, content_hash=row.content_hash, language_code=row.language_code,
            pii_categories=row.pii_categories, corruption_flags=row.corruption_flags,
            label_department=row.label_department, label_priority=row.label_priority,
            label_sentiment=row.label_sentiment, query_text=row.query_text,
            relevant_document_ref=row.relevant_document_ref, relevance_grade=row.relevance_grade,
            split=row.split,
        )
        db.add(orm_row)
        rows_by_index[row.row_index] = orm_row
    await db.flush()
    for row in processed:
        if row.near_duplicate_of is not None and row.near_duplicate_of in rows_by_index:
            rows_by_index[row.row_index].near_duplicate_of = rows_by_index[row.near_duplicate_of].id
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.dataset.imported", resource_type="dataset_version", resource_id=str(version.id), metadata_json={"dataset_id": str(dataset.id), "version_number": next_version, **{k: v for k, v in report.items() if k != "rejection_reasons"}}))
    await db.commit(); await db.refresh(version)
    return {"version": version_json(version), "quality_report": report}


def settings_max_bytes() -> int:
    from app.config import settings
    return settings.dataset_import_max_bytes


def settings_max_rows() -> int:
    from app.config import settings
    return settings.dataset_import_max_rows


@router.get("/{dataset_id}/versions")
async def list_versions(dataset_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "dataset:read")
    await require_lab_enabled(db, user)
    dataset = await db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.tenant_id == user.tenant_id))
    if not dataset:
        raise HTTPException(404, "Dataset not found")
    rows = (await db.scalars(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id).order_by(DatasetVersion.version_number.desc()))).all()
    return {"items": [version_json(row) for row in rows]}


@router.get("/{dataset_id}/versions/{version_id}/rows")
async def list_rows(dataset_id: UUID, version_id: UUID, split: str | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "dataset:read")
    await require_lab_enabled(db, user)
    version = await db.scalar(select(DatasetVersion).join(Dataset, Dataset.id == DatasetVersion.dataset_id).where(DatasetVersion.id == version_id, DatasetVersion.dataset_id == dataset_id, Dataset.tenant_id == user.tenant_id))
    if not version:
        raise HTTPException(404, "Dataset version not found")
    query = select(DatasetRow).where(DatasetRow.dataset_version_id == version_id)
    if split:
        query = query.where(DatasetRow.split == split)
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = (await db.scalars(query.order_by(DatasetRow.row_index).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [{
        "id": row.id, "row_index": row.row_index, "group_key": row.group_key, "redacted_text": row.redacted_text,
        "language_code": row.language_code, "pii_categories": row.pii_categories, "corruption_flags": row.corruption_flags,
        "label_department": row.label_department, "label_priority": row.label_priority, "label_sentiment": row.label_sentiment,
        "query_text": row.query_text, "relevant_document_ref": row.relevant_document_ref, "relevance_grade": row.relevance_grade,
        "split": row.split, "near_duplicate_of": row.near_duplicate_of,
    } for row in rows], "page": page, "page_size": page_size, "total": total}


@router.post("/{dataset_id}/versions/{version_id}/revert", status_code=200)
async def revert_version(dataset_id: UUID, version_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "dataset:manage")
    await require_lab_enabled(db, user)
    version = await db.scalar(select(DatasetVersion).join(Dataset, Dataset.id == DatasetVersion.dataset_id).where(DatasetVersion.id == version_id, DatasetVersion.dataset_id == dataset_id, Dataset.tenant_id == user.tenant_id).with_for_update())
    if not version:
        raise HTTPException(404, "Dataset version not found")
    if version.status == "reverted":
        return version_json(version)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    await db.execute(delete(DatasetRow).where(DatasetRow.dataset_version_id == version_id))
    batches = (await db.scalars(select(DatasetImportBatch).where(DatasetImportBatch.dataset_version_id == version_id))).all()
    for batch in batches:
        batch.reverted_at = now
        batch.reverted_by = user.id
    version.status = "reverted"
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.dataset.version_reverted", resource_type="dataset_version", resource_id=str(version_id), metadata_json={"dataset_id": str(dataset_id)}))
    await db.commit(); await db.refresh(version)
    return version_json(version)
