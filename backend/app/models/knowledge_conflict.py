"""V2 Phase 10: automatic knowledge-conflict detection.

A conflict is a real, computed signal against real KnowledgeBaseDocument
rows, existing citations, and existing outcomes (ResolutionConfirmation,
Feedback edit ratio, Ticket.reopened_count) — never a fabricated finding.
Articles are never auto-deleted or auto-rewritten; a conflict only ever
records a review task and (for open, high/critical-severity conflicts)
blocks the affected article from counting as approved evidence in the
auto-resolution gate — see resolution_policy.py's
no_unresolved_knowledge_conflict gate.
"""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin

CONFLICT_TYPES = ("contradictory_steps", "low_customer_success", "high_engineer_edit_rate", "high_reopen_rate", "unused_long_period")
BLOCKING_SEVERITIES = ("high", "critical")


class KnowledgeConflict(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "knowledge_conflicts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedup_key", name="uq_knowledge_conflict_dedup"),
        CheckConstraint("conflict_type IN ('contradictory_steps','low_customer_success','high_engineer_edit_rate','high_reopen_rate','unused_long_period')", name="ck_knowledge_conflicts_type"),
        CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_knowledge_conflicts_severity"),
        CheckConstraint("review_state IN ('open','reviewing','resolved','dismissed')", name="ck_knowledge_conflicts_review_state"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    article_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False, index=True)
    article_b_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_base.id", ondelete="CASCADE"), index=True)
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_excerpt_a: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_excerpt_b: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))
    sample_size: Mapped[int | None] = mapped_column(Integer)
    affected_ticket_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    review_state: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
