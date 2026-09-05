"""Section 13: versioned smart resolution playbooks (migration 0022).

A playbook is an immutable versioned document, mirroring the same pattern
DepartmentResolutionPolicy already uses: editing never mutates a row in place,
"editing" creates a new draft version referencing the one it supersedes.
Applying a playbook to a ticket copies its diagnostic_steps_template into a
real DiagnosticPlan/DiagnosticStep pair (see services/playbooks.py) rather
than tickets pointing back at the template, so a later playbook edit never
retroactively changes a step already shown to an Engineer.
"""
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin, UpdatedAtMixin


class Playbook(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "playbooks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "playbook_key", "version", name="uq_playbook_key_version"),
        CheckConstraint("status IN ('draft','approved','active','inactive','superseded')", name="ck_playbooks_status"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    playbook_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    applicable_error_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    clarification_questions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence_requirements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    diagnostic_steps_template: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    approved_actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    safety_warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    resolution_template: Mapped[str | None] = mapped_column(Text)
    escalation_rules: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    auto_resolution_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("playbooks.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)


class PlaybookApplication(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "playbook_applications"
    __table_args__ = (
        CheckConstraint("application_type IN ('recommended','applied')", name="ck_playbook_applications_type"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    playbook_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("playbooks.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    diagnostic_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("diagnostic_plans.id", ondelete="SET NULL"))
    applied_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    application_type: Mapped[str] = mapped_column(String(20), nullable=False)
