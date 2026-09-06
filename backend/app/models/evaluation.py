"""V2 Phase 3: reproducible evaluation runs against the dataset registry.

An evaluation run is immutable once completed: it records the exact dataset
version, model artifact hash, environment and git commit it was produced
with, so a metric can always be traced back to what actually generated it.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin


class EvaluationRun(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint("target IN ('department','priority','sentiment')", name="ck_evaluation_runs_target"),
        CheckConstraint("status IN ('completed','failed','insufficient_data')", name="ck_evaluation_runs_status"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(20), nullable=False)
    model_artifact_path: Mapped[str] = mapped_column(String(300), nullable=False)
    model_artifact_hash: Mapped[str | None] = mapped_column(String(64))
    git_commit: Mapped[str | None] = mapped_column(String(40))
    environment_info: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    split_used: Mapped[str] = mapped_column(String(10), nullable=False, default="test")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    row_count_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count_excluded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exclusion_reasons: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class EvaluationExample(Base, UUIDPKMixin):
    __tablename__ = "evaluation_examples"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("dataset_rows.id", ondelete="CASCADE"), nullable=False, index=True)
    true_label: Mapped[str] = mapped_column(String(120), nullable=False)
    predicted_label: Mapped[str] = mapped_column(String(120), nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    top_3_hit: Mapped[bool | None] = mapped_column(Boolean)
    predicted_confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))


class EvaluationMetric(Base, UUIDPKMixin):
    __tablename__ = "evaluation_metrics"
    __table_args__ = (CheckConstraint("scope IN ('overall','per_class')", name="ck_evaluation_metrics_scope"),)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    class_label: Mapped[str | None] = mapped_column(String(120))
    metric_name: Mapped[str] = mapped_column(String(80), nullable=False)
    metric_value: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    support: Mapped[int | None] = mapped_column(Integer)


class EvaluationArtifact(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "evaluation_artifacts"
    __table_args__ = (CheckConstraint("artifact_type IN ('confusion_matrix',)", name="ck_evaluation_artifacts_type"),)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
