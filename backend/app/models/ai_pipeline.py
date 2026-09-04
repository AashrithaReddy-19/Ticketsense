import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin


class PipelineExecution(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "pipeline_executions"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_version: Mapped[str] = mapped_column(String(40), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_duration_ms: Mapped[int | None] = mapped_column(Integer)
    failure_stage: Mapped[str | None] = mapped_column(String(80))
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)


class PipelineStage(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "pipeline_stages"
    __table_args__ = (UniqueConstraint("execution_id", "sequence_number", name="uq_pipeline_stage_sequence"),)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pipeline_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_name: Mapped[str] = mapped_column(String(80), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_summary: Mapped[str | None] = mapped_column(String(300))
    output_summary: Mapped[str | None] = mapped_column(String(500))
    provider_name: Mapped[str | None] = mapped_column(String(100))
    provider_version: Mapped[str | None] = mapped_column(String(120))
    confidence: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(80))
    safe_error_summary: Mapped[str | None] = mapped_column(String(300))
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class TechnicalEntity(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "technical_entities"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    raw_value: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False, default="extracted")
    corrected_from_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("technical_entities.id"))


class ClaimValidation(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "claim_validations"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pipeline_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    response_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("response_drafts.id", ondelete="CASCADE"), index=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    citation_id: Mapped[str | None] = mapped_column(String(40))
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(80), nullable=False)
