"""Enterprise workflow entities introduced by migration 0019.

These tables deliberately extend, rather than replace, the Release A/B models.
Legacy roles and response drafts remain valid while the public product is reduced
to Customer, Engineer, and Admin experiences.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin, UpdatedAtMixin


class EngineerProfile(Base, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "engineer_profiles"
    __table_args__ = (
        CheckConstraint("availability_status IN ('available','busy','away','offline')", name="ck_engineer_profiles_availability"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    availability_status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    max_weighted_capacity: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    availability_schedule: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    performance_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class EngineerSkill(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "engineer_skills"
    __table_args__ = (
        UniqueConstraint("user_id", "department_id", "specialization", name="uq_engineer_skill_scope"),
        CheckConstraint("skill_level IN ('none','basic','intermediate','advanced','expert')", name="ck_engineer_skills_level"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    specialization: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_level: Mapped[str] = mapped_column(String(20), nullable=False, default="intermediate")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class DepartmentResolutionPolicy(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "department_resolution_policies"
    __table_args__ = (
        CheckConstraint("auto_resolve_threshold >= 0 AND auto_resolve_threshold <= 1", name="ck_resolution_policy_threshold"),
        CheckConstraint("minimum_citation_coverage >= 0 AND minimum_citation_coverage <= 1", name="ck_resolution_policy_citations"),
        CheckConstraint("minimum_retrieval_score >= 0 AND minimum_retrieval_score <= 1", name="ck_resolution_policy_retrieval"),
        CheckConstraint("minimum_classification_confidence >= 0 AND minimum_classification_confidence <= 1", name="ck_resolution_policy_classification"),
        CheckConstraint("minimum_classification_margin >= 0 AND minimum_classification_margin <= 1", name="ck_resolution_policy_margin"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), index=True)
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    risk_class: Mapped[str | None] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    allow_auto_resolution: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_resolve_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.85)
    minimum_citation_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    minimum_retrieval_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.65)
    minimum_classification_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.75)
    minimum_classification_margin: Mapped[float] = mapped_column(Float, nullable=False, default=0.15)
    auto_resolution_allowlist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sensitive_category_denylist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class TicketDecision(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "ticket_decisions"
    __table_args__ = (
        UniqueConstraint("ticket_id", "pipeline_execution_id", name="uq_ticket_decision_execution"),
        CheckConstraint("decision IN ('auto_resolve','assign_engineer','admin_intervention','processing_failed')", name="ck_ticket_decisions_decision"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pipeline_executions.id", ondelete="SET NULL"), nullable=True)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("department_resolution_policies.id", ondelete="SET NULL"), nullable=True)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    overall_confidence: Mapped[float | None] = mapped_column(Float)
    applicable_threshold: Mapped[float | None] = mapped_column(Float)
    passed_gates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    failed_gates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    factors: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_fingerprint: Mapped[str | None] = mapped_column(String(64))


class ConfidenceComponent(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "confidence_components"
    __table_args__ = (UniqueConstraint("ticket_decision_id", "component", name="uq_confidence_component_decision"),)
    ticket_decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ticket_decisions.id", ondelete="CASCADE"), nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(80), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str | None] = mapped_column(String(500))


class AssignmentDecision(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "assignment_decisions"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    engineer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    decision_type: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    factor_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class TicketMessage(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "ticket_messages"
    __table_args__ = (
        CheckConstraint("visibility IN ('public','internal')", name="ck_ticket_messages_visibility"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_ticket_messages_idempotency"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    visibility: Mapped[str] = mapped_column(String(10), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    original_language: Mapped[str] = mapped_column(String(12), nullable=False, default="en")
    translated_body: Mapped[str | None] = mapped_column(Text)
    translated_language: Mapped[str | None] = mapped_column(String(12))
    machine_translated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attachment_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    idempotency_key: Mapped[str | None] = mapped_column(String(120))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TicketMessageRead(Base, CreatedAtMixin):
    __tablename__ = "ticket_message_reads"
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ticket_messages.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class ResolutionConfirmation(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "resolution_confirmations"
    __table_args__ = (
        CheckConstraint("outcome IN ('solved','needs_help')", name="ck_resolution_confirmations_outcome"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_resolution_confirmations_idempotency"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    response_fingerprint: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(120))


class DiagnosticPlan(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "diagnostic_plans"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    summary: Mapped[str | None] = mapped_column(Text)


class DiagnosticStep(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "diagnostic_steps"
    __table_args__ = (
        UniqueConstraint("plan_id", "sequence_number", name="uq_diagnostic_step_sequence"),
        CheckConstraint("status IN ('pending','passed','failed','not_applicable','requires_escalation')", name="ck_diagnostic_steps_status"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("diagnostic_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    safety_warning: Mapped[str | None] = mapped_column(Text)
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_note: Mapped[str | None] = mapped_column(Text)
