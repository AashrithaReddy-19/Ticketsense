"""V2 Phase 7: tenant-isolated dependency graph.

Nodes and edges are derived from real, already-persisted relationships
(ticket -> department, ticket -> incident via Ticket.parent_incident_id,
ticket -> playbook via PlaybookApplication, ticket -> knowledge article via
ResponseDraft.citations, ticket -> extracted error code via TechnicalEntity)
by app.services.graph.builder — nothing here is fabricated or synthetic.
PostgreSQL tables are used directly (no separate graph database) per the
spec's "prefer PostgreSQL tables/recursive queries initially" guidance;
a different graph engine could read/write this same shape later without
changing the domain model.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin, UpdatedAtMixin

NODE_TYPES = ("ticket", "department", "incident", "playbook", "knowledge_article", "customer", "error_code")
EDGE_TYPES = ("routed_to", "submitted_by", "clustered_into", "applies_playbook", "cites", "extracted_error_code")


class GraphNode(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "node_type", "external_id", name="uq_graph_node_identity"),
        CheckConstraint("node_type IN ('ticket','department','incident','playbook','knowledge_article','customer','error_code')", name="ck_graph_nodes_type"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_record: Mapped[str] = mapped_column(String(60), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GraphEdge(Base, UUIDPKMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_node_id", "target_node_id", "edge_type", name="uq_graph_edge_identity"),
        CheckConstraint("edge_type IN ('routed_to','submitted_by','clustered_into','applies_playbook','cites','extracted_error_code')", name="ck_graph_edges_type"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    edge_type: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    provenance: Mapped[str | None] = mapped_column(Text)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_record: Mapped[str] = mapped_column(String(60), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
