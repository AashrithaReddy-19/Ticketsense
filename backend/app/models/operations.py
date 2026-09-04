import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin


class DepartmentConfidencePolicy(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "department_confidence_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "department_id", "version", name="uq_department_confidence_version"),
        CheckConstraint("low_threshold >= 0 AND low_threshold <= 1", name="ck_confidence_low_range"),
        CheckConstraint("high_threshold >= 0 AND high_threshold <= 1", name="ck_confidence_high_range"),
        CheckConstraint("low_threshold <= high_threshold", name="ck_confidence_threshold_order"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False, index=True)
    low_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    high_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class PipelineMetric(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "pipeline_metrics"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    provider_version: Mapped[str | None] = mapped_column(String(120))
    error_category: Mapped[str | None] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
