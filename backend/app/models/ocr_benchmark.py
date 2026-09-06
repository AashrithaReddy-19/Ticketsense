"""V2 Phase 11: OCR/multimodal diagnostic benchmark lab.

A tenant-scoped catalog of curated, synthetic ground-truth image/text pairs
(never real customer attachments) and reproducible benchmark runs against
pluggable OCR engines. Every run records the real, live availability of the
engine it targeted — an engine that isn't installed produces an honest
``engine_unavailable`` run, never a fabricated score."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin

OCR_ENGINES = ("tesseract", "easyocr", "paddleocr")


class OcrBenchmarkDataset(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "ocr_benchmark_datasets"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_ocr_benchmark_dataset_key"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class OcrBenchmarkCase(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "ocr_benchmark_cases"
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ocr_benchmark_datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ground_truth_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_label: Mapped[str] = mapped_column(String(20), nullable=False, default="synthetic")
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class OcrBenchmarkRun(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "ocr_benchmark_runs"
    __table_args__ = (
        CheckConstraint(f"engine IN {OCR_ENGINES!r}", name="ck_ocr_benchmark_runs_engine"),
        CheckConstraint("status IN ('completed','engine_unavailable','insufficient_data','failed')", name="ck_ocr_benchmark_runs_status"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ocr_benchmark_datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    engine: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    unavailable_reason: Mapped[str | None] = mapped_column(Text)
    row_count_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mean_character_error_rate: Mapped[float | None] = mapped_column(Numeric(6, 4))
    mean_word_error_rate: Mapped[float | None] = mapped_column(Numeric(6, 4))
    mean_latency_ms: Mapped[float | None] = mapped_column(Numeric(10, 2))
    environment_info: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class OcrBenchmarkResult(Base, UUIDPKMixin):
    __tablename__ = "ocr_benchmark_results"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ocr_benchmark_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ocr_benchmark_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    character_error_rate: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    word_error_rate: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    latency_ms: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
