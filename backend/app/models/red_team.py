"""V2 Phase 9: adversarial AI safety / red-team laboratory.

Suites and cases are a versioned code+data pair: the row here carries the
descriptive metadata (category, severity, expected result) an Admin sees on
the dashboard, while the actual attack payload and check logic live in
app.services.red_team.cases as versioned Python functions keyed by
case_key — the code is the reproducible artifact, the DB row is its
description. Red-team payloads are synthetic test strings only (fake
secrets, fake destructive instructions); nothing here is a real credential,
and no case ever runs against the production knowledge corpus or a real
customer-visible ticket.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin

CATEGORIES = (
    "prompt_injection", "malicious_knowledge_document", "system_prompt_disclosure",
    "fabricated_citations", "cross_tenant_retrieval", "encoded_secrets",
    "unsafe_instructions", "contradictory_knowledge", "tool_parameter_injection",
    "ssrf_path_traversal", "role_escalation",
)


class RedTeamSuite(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "red_team_suites"
    __table_args__ = (UniqueConstraint("suite_key", "version", name="uq_red_team_suite_version"),)
    suite_key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class RedTeamCase(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "red_team_cases"
    __table_args__ = (
        UniqueConstraint("suite_id", "case_key", name="uq_red_team_case_key"),
        CheckConstraint("category IN ('prompt_injection','malicious_knowledge_document','system_prompt_disclosure','fabricated_citations','cross_tenant_retrieval','encoded_secrets','unsafe_instructions','contradictory_knowledge','tool_parameter_injection','ssrf_path_traversal','role_escalation')", name="ck_red_team_cases_category"),
        CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_red_team_cases_severity"),
    )
    suite_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("red_team_suites.id", ondelete="CASCADE"), nullable=False, index=True)
    case_key: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str] = mapped_column(String(40), nullable=False)


class RedTeamRun(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "red_team_runs"
    __table_args__ = (CheckConstraint("status IN ('completed','failed')", name="ck_red_team_runs_status"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    suite_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("red_team_suites.id", ondelete="CASCADE"), nullable=False, index=True)
    suite_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class RedTeamResult(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "red_team_results"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("red_team_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("red_team_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    observed_result: Mapped[str] = mapped_column(String(40), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    gate_responsible: Mapped[str | None] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
