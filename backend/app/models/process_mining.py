"""V2 Phase 14: process mining over the real, immutable ticket_events log.

A run is a point-in-time snapshot of two textbook process-mining views
computed from real TicketEvent rows only: variant discovery (the distinct
event-type sequences tickets actually followed, and how common each is)
and bottleneck analysis (real elapsed-time statistics between consecutive
event-type pairs). Nothing here is inferred, predicted or simulated."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin


class ProcessMiningRun(Base, UUIDPKMixin, CreatedAtMixin):
    __tablename__ = "process_mining_runs"
    __table_args__ = (CheckConstraint("status IN ('completed','insufficient_data')", name="ck_process_mining_runs_status"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    ticket_count_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_count_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    variants: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    bottlenecks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    insufficiency_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
