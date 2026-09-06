"""V2 Phase 6: deterministic counterfactual explanations for resolution
decisions. Generated once per (ticket_decision, explanation_version) and
cached — the explanation is a pure function of already-stored gate data, so
re-generating it would always produce byte-identical output; caching just
avoids recomputing it on every request and gives every explanation a stable
id for audit reference.
"""
import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin


class CounterfactualExplanation(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "counterfactual_explanations"
    __table_args__ = (
        UniqueConstraint("ticket_decision_id", "explanation_version", name="uq_counterfactual_decision_version"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ticket_decisions.id", ondelete="CASCADE"), nullable=False, index=True)
    explanation_version: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    input_passed_gates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    input_failed_gates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    input_factors: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    blocking_gates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    immutable_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence_gaps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    narrative_internal: Mapped[str] = mapped_column(Text, nullable=False)
    narrative_customer: Mapped[str] = mapped_column(Text, nullable=False)
