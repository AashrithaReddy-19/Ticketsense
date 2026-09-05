"""Section 19: safe, allowlisted action framework (migration 0024).

SafeActionDefinition is a global, code-backed capability registry: this table
is metadata only (title, risk, whether it's enabled, whether it requires
approval) — the actual preview/execute logic is Python code in
services/safe_actions.py, keyed by action_key. This table never decides what
code runs; it only decides what's visible/enabled/required around it.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin, UpdatedAtMixin


class SafeActionDefinition(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "safe_action_definitions"
    __table_args__ = (CheckConstraint("risk_level IN ('low','medium','high')", name="ck_safe_action_risk"),)
    action_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    required_capability: Mapped[str] = mapped_column(String(80), nullable=False, default="safe_action:execute")
    parameter_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requires_customer_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    connector: Mapped[str] = mapped_column(String(40), nullable=False, default="internal")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    supports_dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supports_rollback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tenant_scoped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SafeActionExecution(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "safe_action_executions"
    __table_args__ = (
        CheckConstraint("mode IN ('preview','execute')", name="ck_safe_action_mode"),
        CheckConstraint("status IN ('pending','pending_approval','approved','rejected','running','succeeded','failed','timed_out')", name="ck_safe_action_status"),
        UniqueConstraint("tenant_id", "action_key", "idempotency_key", name="uq_safe_action_idempotency"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    action_key: Mapped[str] = mapped_column(String(80), ForeignKey("safe_action_definitions.action_key"), nullable=False)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="SET NULL"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"))
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="execute")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120))
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class SafeActionApproval(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "safe_action_approvals"
    __table_args__ = (CheckConstraint("decision IN ('pending','approved','rejected')", name="ck_safe_action_approval_decision"),)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("safe_action_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SafeActionResult(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "safe_action_results"
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("safe_action_executions.id", ondelete="CASCADE"), nullable=False, unique=True)
    result_summary: Mapped[str] = mapped_column(Text, nullable=False)
    result_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rollback_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rolled_back: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
