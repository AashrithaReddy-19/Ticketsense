import uuid

from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin, UpdatedAtMixin


class Ticket(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint("attachment_type IN ('image','pdf','log')", name="ck_tickets_attachment_type"),
        CheckConstraint("priority IN ('low','medium','high','urgent')", name="ck_tickets_priority"),
        CheckConstraint("sentiment IN ('positive','neutral','negative')", name="ck_tickets_sentiment"),
        CheckConstraint(
            "status IN ('submitted','needs_clarification','ai_processing','awaiting_assignment','assigned','in_progress','awaiting_customer','escalated','resolved_by_ai','resolved_by_engineer','reopened','closed','ai_processing_failed','processing','classified','routed','pending_review','changes_requested','approved','resolved')", name="ck_tickets_status"
        ),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True)
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attachment_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted", index=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    required_specialization: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    resolution_type: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    auto_resolution_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_resolution_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reopened_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    parent_incident_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True)
    last_auto_resolution_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    complexity_weight: Mapped[float] = mapped_column(Numeric, nullable=False, default=1.0)
    ai_draft_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    final_response_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    final_responder_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    final_approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    public_status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    # Snapshot of the feature vector used for the confidence prediction (retrieval relevance,
    # ticket-to-resolution similarity, document freshness, OCR confidence, category risk), so
    # human Accept/Edit/Reject/Escalate outcomes can be joined back to it for retraining.
    confidence_features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    assignment_reason: Mapped[str | None] = mapped_column(Text)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    analysis_status: Mapped[str] = mapped_column(String(30), default="complete")
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(Text)
    escalation_level: Mapped[str | None] = mapped_column(String(30))
    routing_state: Mapped[str] = mapped_column(String(30), default="routed")
    sensitivity: Mapped[str] = mapped_column(String(30), default="internal")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
