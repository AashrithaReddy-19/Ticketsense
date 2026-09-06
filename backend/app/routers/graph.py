"""TicketSense V2 dependency graph API.

Every response includes an explicit disclaimer: an edge with confirmed=false
is an inferred relationship (e.g. a duplicate-ticket cluster nobody has
reviewed yet), not a confirmed fact. Traversal depth/result counts are
always capped server-side regardless of what a caller requests, and
authorization is re-checked at every hop against live tables — see
app.services.graph.traversal for why that matters.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, user_has_permission
from app.models.platform import AuditLog
from app.models.user import User
from app.services.feature_flags import require_feature
from app.services.graph.builder import rebuild_tenant_graph
from app.services.graph.traversal import TraversalResult, blast_radius, neighborhood
from app.services.ticket_visibility import get_visible_ticket

router = APIRouter(prefix="/api/v2/graph", tags=["v2-graph"])

DISCLAIMER = "Edges marked confirmed=false are inferred relationships (e.g. an unreviewed duplicate-ticket cluster), not confirmed facts."


async def require(db: AsyncSession, user: User, capability: str) -> None:
    if not await user_has_permission(db, user, capability):
        raise HTTPException(403, f"Permission required: {capability}")


async def require_flag_enabled(db: AsyncSession, user: User) -> None:
    from app.routers.auth import _permissions
    permissions = await _permissions(db, user)
    await require_feature(db, "graphrag", user, permissions)


def result_json(result: TraversalResult) -> dict:
    return {
        "nodes": result.nodes, "edges": result.edges, "truncated": result.truncated,
        "depth_reached": result.depth_reached, "disclaimer": DISCLAIMER,
    }


@router.get("/tickets/{ticket_id}")
async def ticket_neighborhood(ticket_id: UUID, max_depth: int = Query(2, ge=1, le=3), max_results: int = Query(50, ge=1, le=200), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_flag_enabled(db, user)
    ticket = await get_visible_ticket(db, user, ticket_id)
    result = await neighborhood(db, user, ticket.id, max_depth=max_depth, max_results=max_results)
    return result_json(result)


@router.get("/incidents/{incident_id}/blast-radius")
async def incident_blast_radius(incident_id: UUID, max_results: int = Query(100, ge=1, le=200), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_flag_enabled(db, user)
    await require(db, user, "graph:read")
    result = await blast_radius(db, user, incident_id, max_results=max_results)
    return result_json(result)


@router.post("/rebuild")
async def rebuild_graph(limit: int = Query(500, ge=1, le=2000), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_flag_enabled(db, user)
    await require(db, user, "graph:manage")
    stats = await rebuild_tenant_graph(db, user.tenant_id, limit=limit)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="v2.graph.rebuilt", resource_type="graph", resource_id=None, metadata_json=stats))
    await db.commit()
    return stats
