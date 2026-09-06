"""V2 Phase 8: shadow-mode sampling and champion/challenger comparison.

A ShadowRun never touches ticket state — it is a private, redacted-input
comparison of what a champion and challenger model would each say about a
ticket's already-existing text, recorded purely for later Admin review.
Nothing here is ever surfaced to a customer or used to route/resolve a
ticket; see app.services.experiments.shadow for the read-only guarantee.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin


class ShadowRun(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "shadow_runs"
    __table_args__ = (
        CheckConstraint("task_type IN ('department','priority','sentiment')", name="ck_shadow_runs_task"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(20), nullable=False)
    champion_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("provider_models.id", ondelete="SET NULL"))
    challenger_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("provider_models.id", ondelete="SET NULL"))
    redacted_input: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_label: Mapped[str | None] = mapped_column(String(160))
    champion_output: Mapped[str | None] = mapped_column(String(160))
    champion_confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))
    champion_latency_ms: Mapped[int | None] = mapped_column(Integer)
    challenger_output: Mapped[str | None] = mapped_column(String(160))
    challenger_confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))
    challenger_latency_ms: Mapped[int | None] = mapped_column(Integer)
    agreement: Mapped[bool | None] = mapped_column(Boolean)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
