"""Section 20: evidence-backed predictive-prevention recommendations
(migration 0025). See that migration's docstring for why recommendation
review state lives on PreventionRecommendation directly rather than in a
separate 1:1 "reviews" table.
"""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin, UpdatedAtMixin


class PreventionRecommendation(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "prevention_recommendations"
    __table_args__ = (
        CheckConstraint(
            "recommendation_type IN ('create_knowledge_article','update_knowledge_article','investigate_version',"
            "'publish_customer_announcement','conduct_training','add_monitoring','review_capacity_allocation',"
            "'investigate_infrastructure')",
            name="ck_prevention_rec_type",
        ),
        CheckConstraint("evidence_strength IN ('low','medium','high')", name="ck_prevention_rec_strength"),
        CheckConstraint("status IN ('new','under_investigation','accepted','rejected','dismissed','converted')", name="ck_prevention_rec_status"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"))
    category: Mapped[str | None] = mapped_column(String(120))
    recommendation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    supporting_ticket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_strength: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_benefit: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="new")
    decision_reason: Mapped[str | None] = mapped_column(Text)
    linked_incident_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"))
    linked_knowledge_article_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_articles.id", ondelete="SET NULL"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecommendationEvidence(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "recommendation_evidence"
    recommendation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prevention_recommendations.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(60), nullable=False)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class RecommendationAction(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "recommendation_actions"
    __table_args__ = (CheckConstraint("action_type IN ('accept','reject','investigate','dismiss','convert_to_knowledge','link_incident')", name="ck_recommendation_action_type"),)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prevention_recommendations.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    result_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
