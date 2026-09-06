"""Builds tenant-isolated graph nodes/edges from real, already-persisted
relationships. Every edge type maps to a specific existing column or table:

- routed_to: Ticket.department_id
- submitted_by: Ticket.submitted_by
- clustered_into: Ticket.parent_incident_id (set by services/incidents.py's
  duplicate-clustering; confirmed only when an Admin set Incident.confirmed_at)
- applies_playbook: PlaybookApplication rows (confirmed only for
  application_type == "applied", not "recommended")
- cites: ResponseDraft.citations entries that carry a real article_id
  resolving to a knowledge_base row (entries without one — degraded/legacy
  inline-only citations — are skipped rather than guessed at)
- extracted_error_code: TechnicalEntity rows with entity_type == "error_code"

Nothing here invents a relationship; a get-or-create sync only ever reads
what already exists elsewhere and mirrors it as a node/edge.
"""
import uuid
from datetime import datetime, timezone
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_pipeline import TechnicalEntity
from app.models.department import Department
from app.models.graph import GraphEdge, GraphNode
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.platform import Incident
from app.models.playbook import Playbook, PlaybookApplication
from app.models.response_draft import ResponseDraft
from app.models.ticket import Ticket
from app.models.user import User

# Fixed namespace for deterministic synthetic ids on value-keyed nodes (error
# codes have no single owning row) — stable across process restarts.
ERROR_CODE_NAMESPACE = uuid.UUID("6f6b1a2e-2f1a-4b0b-9c1a-8e2d6a2b7c11")


async def _get_or_create_node(db: AsyncSession, tenant_id, node_type: str, external_id, label: str, attributes: dict, source_record: str, confirmed: bool) -> GraphNode:
    now = datetime.now(timezone.utc)
    node = await db.scalar(select(GraphNode).where(GraphNode.tenant_id == tenant_id, GraphNode.node_type == node_type, GraphNode.external_id == external_id))
    if node:
        node.label, node.attributes, node.confirmed, node.last_seen = label, attributes, confirmed, now
        return node
    node = GraphNode(tenant_id=tenant_id, node_type=node_type, external_id=external_id, label=label, attributes=attributes, source_record=source_record, confirmed=confirmed, first_seen=now, last_seen=now)
    db.add(node)
    await db.flush()
    return node


async def _get_or_create_edge(db: AsyncSession, tenant_id, source: GraphNode, target: GraphNode, edge_type: str, confidence: float | None, provenance: str | None, confirmed: bool, source_record: str) -> GraphEdge:
    now = datetime.now(timezone.utc)
    edge = await db.scalar(select(GraphEdge).where(GraphEdge.tenant_id == tenant_id, GraphEdge.source_node_id == source.id, GraphEdge.target_node_id == target.id, GraphEdge.edge_type == edge_type))
    if edge:
        edge.confidence, edge.provenance, edge.confirmed, edge.last_seen = confidence, provenance, confirmed, now
        return edge
    edge = GraphEdge(tenant_id=tenant_id, source_node_id=source.id, target_node_id=target.id, edge_type=edge_type, confidence=confidence, provenance=provenance, confirmed=confirmed, source_record=source_record, first_seen=now, last_seen=now)
    db.add(edge)
    await db.flush()
    return edge


async def sync_ticket_graph(db: AsyncSession, ticket: Ticket) -> GraphNode:
    """Refresh every graph node/edge derivable from this one ticket's current
    state. Safe to call repeatedly (get-or-create throughout)."""
    ticket_node = await _get_or_create_node(
        db, ticket.tenant_id, "ticket", ticket.id, ticket.subject[:300],
        {"status": ticket.status, "priority": ticket.priority, "category": ticket.category}, "tickets", confirmed=True,
    )

    if ticket.department_id:
        department = await db.get(Department, ticket.department_id)
        if department:
            dept_node = await _get_or_create_node(db, ticket.tenant_id, "department", department.id, department.name, {}, "departments", confirmed=True)
            await _get_or_create_edge(db, ticket.tenant_id, ticket_node, dept_node, "routed_to", None, "Ticket department assignment", True, "tickets.department_id")

    if ticket.submitted_by:
        customer = await db.get(User, ticket.submitted_by)
        if customer:
            customer_node = await _get_or_create_node(db, ticket.tenant_id, "customer", customer.id, customer.full_name, {}, "users", confirmed=True)
            await _get_or_create_edge(db, ticket.tenant_id, ticket_node, customer_node, "submitted_by", None, "Ticket submitter", True, "tickets.submitted_by")

    if ticket.parent_incident_id:
        incident = await db.get(Incident, ticket.parent_incident_id)
        if incident:
            incident_node = await _get_or_create_node(
                db, ticket.tenant_id, "incident", incident.id, incident.title,
                {"status": incident.status, "severity": incident.severity}, "incidents", confirmed=bool(incident.confirmed_at),
            )
            await _get_or_create_edge(
                db, ticket.tenant_id, ticket_node, incident_node, "clustered_into", None,
                incident.detection_reason, bool(incident.confirmed_at), "tickets.parent_incident_id",
            )

    applications = (await db.scalars(select(PlaybookApplication).where(PlaybookApplication.ticket_id == ticket.id))).all()
    for application in applications:
        playbook = await db.get(Playbook, application.playbook_id)
        if playbook:
            playbook_node = await _get_or_create_node(
                db, ticket.tenant_id, "playbook", playbook.id, playbook.title,
                {"category": playbook.category, "version": playbook.version, "status": playbook.status}, "playbooks", confirmed=True,
            )
            await _get_or_create_edge(
                db, ticket.tenant_id, ticket_node, playbook_node, "applies_playbook", None,
                f"Playbook {application.application_type} for this ticket", application.application_type == "applied", "playbook_applications",
            )

    drafts = (await db.scalars(select(ResponseDraft).where(ResponseDraft.ticket_id == ticket.id))).all()
    for draft in drafts:
        for citation in (draft.citations or []):
            if not isinstance(citation, dict):
                continue
            article_id = citation.get("article_id")
            if not article_id:
                continue  # degraded/legacy inline-only citation with no resolvable article — skip rather than guess
            try:
                article_uuid = UUID(str(article_id))
            except ValueError:
                continue
            article = await db.get(KnowledgeBaseDocument, article_uuid)
            if not article:
                continue
            article_node = await _get_or_create_node(
                db, ticket.tenant_id, "knowledge_article", article.id, article.title,
                {"version": article.version, "status": article.status, "is_publishable": article.is_publishable}, "knowledge_base", confirmed=True,
            )
            await _get_or_create_edge(db, ticket.tenant_id, ticket_node, article_node, "cites", None, f"Cited in response draft v{draft.version_number}", True, "response_drafts.citations")

    entities = (await db.scalars(
        select(TechnicalEntity).where(TechnicalEntity.ticket_id == ticket.id, TechnicalEntity.entity_type == "error_code", TechnicalEntity.corrected_from_id.is_(None))
    )).all()
    for entity in entities:
        code_external_id = uuid5(ERROR_CODE_NAMESPACE, f"{ticket.tenant_id}:{entity.normalized_value.lower()}")
        code_node = await _get_or_create_node(db, ticket.tenant_id, "error_code", code_external_id, entity.normalized_value, {}, "technical_entities", confirmed=(entity.validation_status == "corrected"))
        await _get_or_create_edge(
            db, ticket.tenant_id, ticket_node, code_node, "extracted_error_code", entity.confidence,
            f"Extracted via {entity.extraction_method}", entity.validation_status == "corrected", "technical_entities",
        )

    return ticket_node


async def rebuild_tenant_graph(db: AsyncSession, tenant_id, limit: int = 500) -> dict:
    from sqlalchemy import func

    tickets = (await db.scalars(select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.deleted_at.is_(None)).order_by(Ticket.updated_at.desc()).limit(limit))).all()
    for ticket in tickets:
        await sync_ticket_graph(db, ticket)
    node_count = int(await db.scalar(select(func.count()).select_from(GraphNode).where(GraphNode.tenant_id == tenant_id)) or 0)
    edge_count = int(await db.scalar(select(func.count()).select_from(GraphEdge).where(GraphEdge.tenant_id == tenant_id)) or 0)
    return {"tickets_processed": len(tickets), "node_count": node_count, "edge_count": edge_count}
