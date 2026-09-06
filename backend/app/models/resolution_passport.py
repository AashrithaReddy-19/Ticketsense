"""V2 Phase 5: immutable Resolution Passport.

A passport row is never updated after insert — every field on it is a
snapshot taken at the moment a ticket was resolved (by the AI auto-resolution
path or a human engineer's approval), and its own ``integrity_hash`` lets
anyone later verify the row hasn't been altered. When a ticket is resolved
again after a reopen, a new passport is inserted and the old one is marked
``is_current=False`` with ``supersedes_passport_id``/``previous_passport_hash``
pointing at it — the old row itself is still never modified.

Customer confirmation/reopen outcome is deliberately NOT a column here: it
happens asynchronously after the passport is created, so storing it would
either require mutating an "immutable" row or risk it going stale after a
second confirmation. It's joined in at read time instead (see
``app.services.passport.customer_view``).
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin


class ResolutionPassport(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "resolution_passports"
    __table_args__ = (
        CheckConstraint("resolution_type IN ('ai','engineer')", name="ck_resolution_passports_type"),
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    resolution_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_backfilled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supersedes_passport_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("resolution_passports.id", ondelete="SET NULL"))
    previous_passport_hash: Mapped[str | None] = mapped_column(String(64))

    input_content_hash: Mapped[str | None] = mapped_column(String(64))
    classification_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    pipeline_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pipeline_executions.id", ondelete="SET NULL"))
    ticket_decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ticket_decisions.id", ondelete="SET NULL"))
    response_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("response_drafts.id", ondelete="SET NULL"))
    response_version_number: Mapped[int | None] = mapped_column(Integer)
    response_content_hash: Mapped[str | None] = mapped_column(String(64))

    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    claim_validations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confidence_components: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    overall_confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))
    applicable_threshold: Mapped[float | None] = mapped_column(Numeric(6, 4))
    passed_gates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    failed_gates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("department_resolution_policies.id", ondelete="SET NULL"))
    policy_version: Mapped[int | None] = mapped_column(Integer)

    engineer_edit_ratio: Mapped[float | None] = mapped_column(Numeric(6, 4))
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("feedback.id", ondelete="SET NULL"))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
