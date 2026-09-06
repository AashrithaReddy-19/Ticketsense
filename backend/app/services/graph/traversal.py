"""Bounded, tenant-safe graph traversal for dependency context and blast
radius. Authorization is re-checked at every hop against live tables, never
trusted from a graph node's own (possibly stale) attributes snapshot — a
node created when a knowledge article was approved must not still be
exposed after that article is later unpublished, and a customer must never
reach another customer's ticket through a shared incident.

Every edge with confirmed=False is an inferred relationship, not a
confirmed fact, and the response always says so explicitly.
"""
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import is_customer
from app.models.graph import GraphEdge, GraphNode
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.ticket import Ticket
from app.models.user import User
from app.services.ticket_visibility import visibility_conditions

HARD_MAX_DEPTH = 3
HARD_MAX_RESULTS = 200
CUSTOMER_MAX_DEPTH = 1
# Customers may see their own ticket's context but never another customer's
# identity or another ticket reached through a shared incident/playbook.
CUSTOMER_HIDDEN_NODE_TYPES = {"customer"}


@dataclass
class TraversalResult:
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    truncated: bool = False
    depth_reached: int = 0


def _node_json(node: GraphNode) -> dict:
    return {
        "id": node.id, "node_type": node.node_type, "external_id": node.external_id, "label": node.label,
        "attributes": node.attributes, "confirmed": node.confirmed,
    }


async def _authorized_node_ids(db: AsyncSession, user: User, candidates: list[GraphNode]) -> set:
    """Re-verifies each candidate node against live authorization state,
    returning only the ids that pass. Ticket nodes are checked against the
    same visibility rule used everywhere else in the product; knowledge
    article nodes are re-checked against their current (not cached)
    approved/publishable status; every other node type only needs the
    tenant match the caller already enforced."""
    allowed: set = set()
    ticket_external_ids = [n.external_id for n in candidates if n.node_type == "ticket"]
    article_external_ids = [n.external_id for n in candidates if n.node_type == "knowledge_article"]

    visible_ticket_ids: set = set()
    if ticket_external_ids:
        rows = (await db.scalars(
            select(Ticket.id).where(visibility_conditions(user), Ticket.id.in_(ticket_external_ids))
        )).all()
        visible_ticket_ids = set(rows)

    approved_article_ids: set = set()
    if article_external_ids:
        rows = (await db.scalars(
            select(KnowledgeBaseDocument.id).where(
                KnowledgeBaseDocument.id.in_(article_external_ids),
                KnowledgeBaseDocument.status == "approved", KnowledgeBaseDocument.is_publishable.is_(True),
            )
        )).all()
        approved_article_ids = set(rows)

    for node in candidates:
        if node.node_type == "ticket":
            if node.external_id in visible_ticket_ids:
                allowed.add(node.id)
        elif node.node_type == "knowledge_article":
            if node.external_id in approved_article_ids:
                allowed.add(node.id)
        elif is_customer(user.role) and node.node_type in CUSTOMER_HIDDEN_NODE_TYPES:
            continue
        else:
            allowed.add(node.id)
    return allowed


async def neighborhood(db: AsyncSession, user: User, root_ticket_id, max_depth: int = 2, max_results: int = 50) -> TraversalResult:
    depth_cap = min(max_depth, CUSTOMER_MAX_DEPTH if is_customer(user.role) else HARD_MAX_DEPTH)
    result_cap = min(max_results, HARD_MAX_RESULTS)

    root = await db.scalar(select(GraphNode).where(GraphNode.tenant_id == user.tenant_id, GraphNode.node_type == "ticket", GraphNode.external_id == root_ticket_id))
    result = TraversalResult()
    if not root:
        return result

    authorized_root_ids = await _authorized_node_ids(db, user, [root])
    if root.id not in authorized_root_ids:
        return result  # not this user's ticket to see, even though a node exists

    seen_node_ids = {root.id}
    node_by_id = {root.id: root}
    frontier = [root.id]
    result.nodes.append(_node_json(root))

    for depth in range(1, depth_cap + 1):
        if not frontier or len(result.edges) >= result_cap:
            break
        edges = (await db.scalars(
            select(GraphEdge).where(GraphEdge.tenant_id == user.tenant_id, GraphEdge.source_node_id.in_(frontier))
            .order_by(GraphEdge.confirmed.desc(), GraphEdge.last_seen.desc()).limit(result_cap - len(result.edges))
        )).all()
        if not edges:
            break
        candidate_target_ids = {edge.target_node_id for edge in edges} - seen_node_ids
        candidate_targets = []
        if candidate_target_ids:
            candidate_targets = (await db.scalars(select(GraphNode).where(GraphNode.id.in_(candidate_target_ids)))).all()
        authorized_ids = await _authorized_node_ids(db, user, candidate_targets)
        for node in candidate_targets:
            node_by_id[node.id] = node

        next_frontier = []
        for edge in edges:
            target = node_by_id.get(edge.target_node_id)
            if target is None or (edge.target_node_id not in seen_node_ids and edge.target_node_id not in authorized_ids):
                continue
            if edge.target_node_id not in seen_node_ids:
                seen_node_ids.add(edge.target_node_id)
                result.nodes.append(_node_json(target))
                next_frontier.append(edge.target_node_id)
            source = node_by_id[edge.source_node_id]
            result.edges.append({
                "id": edge.id, "source_node_id": edge.source_node_id, "target_node_id": edge.target_node_id,
                "edge_type": edge.edge_type, "confidence": float(edge.confidence) if edge.confidence is not None else None,
                "provenance": edge.provenance, "confirmed": edge.confirmed,
                "path": f"{source.label} --{edge.edge_type}--> {target.label}",
            })
            if len(result.edges) >= result_cap:
                break
        frontier = next_frontier
        result.depth_reached = depth
        if len(result.edges) >= result_cap:
            result.truncated = True
            break

    return result


async def blast_radius(db: AsyncSession, user: User, incident_external_id, max_results: int = 100) -> TraversalResult:
    """Every ticket clustered into this incident, plus each ticket's
    extracted error codes — the shared-symptom evidence an Admin would use
    to judge whether the cluster is a real incident. Never available to a
    customer: an incident spans other customers' tickets by definition."""
    result = TraversalResult()
    if is_customer(user.role):
        return result
    result_cap = min(max_results, HARD_MAX_RESULTS)

    incident_node = await db.scalar(select(GraphNode).where(GraphNode.tenant_id == user.tenant_id, GraphNode.node_type == "incident", GraphNode.external_id == incident_external_id))
    if not incident_node:
        return result
    result.nodes.append(_node_json(incident_node))

    member_edges = (await db.scalars(
        select(GraphEdge).where(GraphEdge.tenant_id == user.tenant_id, GraphEdge.target_node_id == incident_node.id, GraphEdge.edge_type == "clustered_into")
        .order_by(GraphEdge.last_seen.desc()).limit(result_cap)
    )).all()
    if not member_edges:
        return result

    ticket_node_ids = [edge.source_node_id for edge in member_edges]
    ticket_nodes = (await db.scalars(select(GraphNode).where(GraphNode.id.in_(ticket_node_ids)))).all()
    authorized_ids = await _authorized_node_ids(db, user, ticket_nodes)
    node_by_id = {n.id: n for n in ticket_nodes}

    for edge in member_edges:
        ticket_node = node_by_id.get(edge.source_node_id)
        if ticket_node is None or edge.source_node_id not in authorized_ids:
            continue
        result.nodes.append(_node_json(ticket_node))
        result.edges.append({
            "id": edge.id, "source_node_id": edge.source_node_id, "target_node_id": edge.target_node_id,
            "edge_type": edge.edge_type, "confidence": None, "provenance": edge.provenance, "confirmed": edge.confirmed,
            "path": f"{ticket_node.label} --{edge.edge_type}--> {incident_node.label}",
        })
        if len(result.edges) >= result_cap:
            result.truncated = True
            break

    authorized_ticket_ids = [n.id for n in ticket_nodes if n.id in authorized_ids]
    if authorized_ticket_ids:
        symptom_edges = (await db.scalars(
            select(GraphEdge).where(GraphEdge.tenant_id == user.tenant_id, GraphEdge.source_node_id.in_(authorized_ticket_ids), GraphEdge.edge_type == "extracted_error_code")
            .limit(result_cap)
        )).all()
        symptom_node_ids = {edge.target_node_id for edge in symptom_edges}
        symptom_nodes = (await db.scalars(select(GraphNode).where(GraphNode.id.in_(symptom_node_ids)))).all() if symptom_node_ids else []
        symptom_by_id = {n.id: n for n in symptom_nodes}
        for node in symptom_nodes:
            result.nodes.append(_node_json(node))
        for edge in symptom_edges:
            source = node_by_id.get(edge.source_node_id)
            target = symptom_by_id.get(edge.target_node_id)
            if not source or not target:
                continue
            result.edges.append({
                "id": edge.id, "source_node_id": edge.source_node_id, "target_node_id": edge.target_node_id,
                "edge_type": edge.edge_type, "confidence": float(edge.confidence) if edge.confidence is not None else None,
                "provenance": edge.provenance, "confirmed": edge.confirmed,
                "path": f"{source.label} --{edge.edge_type}--> {target.label}",
            })

    result.depth_reached = 2
    return result
