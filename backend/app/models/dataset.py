"""TicketSense V2 dataset registry: versioned, leakage-safe evaluation datasets.

Two dataset kinds are supported: ``ticket_labels`` (support-ticket text plus
department/priority/sentiment labels, for classification evaluation) and
``retrieval_judgments`` (query plus relevant-document judgments, for RAG
retrieval metrics). Both share the same ingestion, redaction, deduplication
and leakage-safe-split pipeline in ``app.services.evaluation.ingestion``.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin, UpdatedAtMixin


class Dataset(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_dataset_key"),
        CheckConstraint("kind IN ('ticket_labels','retrieval_judgments')", name="ck_datasets_kind"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    license_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class DatasetVersion(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version_number"),
        CheckConstraint("status IN ('processing','ready','reverted','failed')", name="ck_dataset_versions_status"),
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label_distribution: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    missing_data_stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    duplicate_rate: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, default=0)
    corruption_rate: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, default=0)
    near_duplicate_cross_split_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    near_duplicate_check_skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    split_ratio: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    split_seed: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class DatasetImportBatch(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "dataset_import_batches"
    __table_args__ = (
        CheckConstraint("source_format IN ('csv','json','jsonl')", name="ck_dataset_import_batches_format"),
    )
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    source_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    source_format: Mapped[str] = mapped_column(String(10), nullable=False)
    raw_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rejection_reasons: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class DatasetRow(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "dataset_rows"
    __table_args__ = (
        CheckConstraint("split IN ('train','validation','test')", name="ck_dataset_rows_split"),
    )
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    import_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("dataset_import_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    group_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    redacted_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    near_duplicate_of: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("dataset_rows.id", ondelete="SET NULL"))
    language_code: Mapped[str] = mapped_column(String(8), nullable=False, default="unknown")
    pii_categories: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    corruption_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    label_department: Mapped[str | None] = mapped_column(String(120))
    label_priority: Mapped[str | None] = mapped_column(String(20))
    label_sentiment: Mapped[str | None] = mapped_column(String(20))
    query_text: Mapped[str | None] = mapped_column(Text)
    relevant_document_ref: Mapped[str | None] = mapped_column(String(200))
    relevance_grade: Mapped[int | None] = mapped_column(Integer)
    split: Mapped[str] = mapped_column(String(10), nullable=False)
