"""Marketplace: discovery, access requests and lineage."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    AccessRequest,
    AccessRequestStatus,
    Component,
    ComponentKind,
    DataProduct,
    Domain,
    LifecycleState,
    LineageEdge,
    User,
)
from app.services import catalog


class AccessError(Exception):
    pass


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------
def search(
    db: Session,
    *,
    query: str = "",
    domain: str | None = None,
    tag: str | None = None,
    technology: str | None = None,
    include_unpublished: bool = False,
) -> list[DataProduct]:
    stmt = select(DataProduct)
    if not include_unpublished:
        stmt = stmt.where(DataProduct.lifecycle == LifecycleState.PUBLISHED)
    if domain:
        stmt = stmt.join(Domain, DataProduct.domain_id == Domain.id).where(Domain.name == domain)
    if query:
        like = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                DataProduct.name.ilike(like),
                DataProduct.title.ilike(like),
                DataProduct.description.ilike(like),
                DataProduct.urn.ilike(like),
            )
        )
    products = list(db.execute(stmt.order_by(DataProduct.title)).scalars().unique())
    if tag:
        products = [p for p in products if tag in (p.tags or [])]
    if technology:
        products = [
            p for p in products
            if any(c.technology == technology and c.kind == ComponentKind.OUTPUT_PORT for c in p.components)
        ]
    return products


def facets(db: Session) -> dict:
    published = search(db)
    tags: dict[str, int] = {}
    technologies: dict[str, int] = {}
    domains: dict[str, int] = {}
    for dp in published:
        domains[dp.domain.name] = domains.get(dp.domain.name, 0) + 1
        for tag in dp.tags or []:
            tags[tag] = tags.get(tag, 0) + 1
        for component in dp.components:
            if component.kind == ComponentKind.OUTPUT_PORT and component.technology:
                technologies[component.technology] = technologies.get(component.technology, 0) + 1
    as_list = lambda d: [{"value": k, "count": v} for k, v in sorted(d.items(), key=lambda kv: -kv[1])]  # noqa: E731
    return {"domains": as_list(domains), "tags": as_list(tags), "technologies": as_list(technologies)}


# --------------------------------------------------------------------------
# access
# --------------------------------------------------------------------------
def request_access(
    db: Session,
    *,
    dp: DataProduct,
    component: Component | None,
    requester: User,
    purpose: str,
    consumer_dp_urn: str = "",
) -> AccessRequest:
    if dp.lifecycle != LifecycleState.PUBLISHED:
        raise AccessError("access can only be requested for a published data product")
    if component is not None and component.kind != ComponentKind.OUTPUT_PORT:
        raise AccessError("access is granted on output ports only")
    if dp.owner_id == requester.id:
        raise AccessError("you already own this data product")

    existing = db.execute(
        select(AccessRequest).where(
            AccessRequest.data_product_id == dp.id,
            AccessRequest.requester_id == requester.id,
            AccessRequest.component_id == (component.id if component else None),
            AccessRequest.status.in_([AccessRequestStatus.PENDING, AccessRequestStatus.APPROVED]),
        )
    ).scalars().first()
    if existing:
        raise AccessError(
            "you already have a "
            f"{'pending' if existing.status == AccessRequestStatus.PENDING else 'granted'} "
            "request for this output port"
        )

    request = AccessRequest(
        data_product_id=dp.id,
        component_id=component.id if component else None,
        requester_id=requester.id,
        purpose=purpose,
        consumer_dp_urn=consumer_dp_urn,
    )
    db.add(request)
    db.flush()
    catalog.record_event(
        db,
        type_="access.requested",
        message=f"{requester.display_name} requested access to "
        f"'{component.title if component else dp.title}'",
        actor=requester,
        data_product=dp,
        payload={"requestId": request.id, "component": component.name if component else None},
    )
    return request


def decide(
    db: Session, request: AccessRequest, *, approve: bool, decider: User, note: str = ""
) -> AccessRequest:
    if request.status != AccessRequestStatus.PENDING:
        raise AccessError("this request has already been decided")
    request.status = AccessRequestStatus.APPROVED if approve else AccessRequestStatus.REJECTED
    request.decided_by_id = decider.id
    request.decided_at = datetime.now(timezone.utc)
    request.decision_note = note
    db.flush()
    catalog.record_event(
        db,
        type_="access.decided",
        message=f"Access request from {request.requester.display_name} "
        f"{'approved' if approve else 'rejected'}",
        actor=decider,
        data_product=request.data_product,
        payload={"requestId": request.id, "approved": approve},
    )
    return request


def revoke(db: Session, request: AccessRequest, *, actor: User, note: str = "") -> AccessRequest:
    if request.status != AccessRequestStatus.APPROVED:
        raise AccessError("only a granted access can be revoked")
    request.status = AccessRequestStatus.REVOKED
    request.decided_by_id = actor.id
    request.decided_at = datetime.now(timezone.utc)
    request.decision_note = note
    db.flush()
    catalog.record_event(
        db, type_="access.revoked", message=f"Access for {request.requester.display_name} revoked",
        actor=actor, data_product=request.data_product, payload={"requestId": request.id},
    )
    return request


def granted_ports(db: Session, user: User) -> list[AccessRequest]:
    return list(
        db.execute(
            select(AccessRequest)
            .where(AccessRequest.requester_id == user.id, AccessRequest.status == AccessRequestStatus.APPROVED)
            .order_by(AccessRequest.decided_at.desc())
        ).scalars()
    )


def has_access(db: Session, user: User, component: Component) -> bool:
    if component.data_product.owner_id == user.id:
        return True
    return db.execute(
        select(AccessRequest).where(
            AccessRequest.component_id == component.id,
            AccessRequest.requester_id == user.id,
            AccessRequest.status == AccessRequestStatus.APPROVED,
        )
    ).scalars().first() is not None


# --------------------------------------------------------------------------
# lineage
# --------------------------------------------------------------------------
def lineage_graph(db: Session, root: DataProduct | None = None, depth: int = 2) -> dict:
    """Nodes and edges of the consumption graph.

    Without a root the whole mesh is returned; with a root the graph is
    limited to `depth` hops upstream and downstream.
    """
    products = {dp.urn: dp for dp in db.execute(select(DataProduct)).scalars().unique()}
    edges = list(db.execute(select(LineageEdge)).scalars())

    by_source: dict[str, list[LineageEdge]] = {}
    by_target: dict[str, list[LineageEdge]] = {}
    id_to_urn = {dp.id: dp.urn for dp in products.values()}
    for edge in edges:
        source_urn = id_to_urn.get(edge.source_dp_id)
        if source_urn is None:
            continue
        by_source.setdefault(source_urn, []).append(edge)
        by_target.setdefault(edge.target_dp_urn, []).append(edge)

    if root is None:
        included = set(products)
    else:
        included = {root.urn}
        frontier = {root.urn}
        for _ in range(max(depth, 0)):
            nxt: set[str] = set()
            for urn in frontier:
                for edge in by_source.get(urn, []):
                    nxt.add(edge.target_dp_urn)
                for edge in by_target.get(urn, []):
                    source_urn = id_to_urn.get(edge.source_dp_id)
                    if source_urn:
                        nxt.add(source_urn)
            nxt -= included
            included |= nxt
            frontier = nxt
            if not frontier:
                break

    nodes = []
    for urn in sorted(included):
        dp = products.get(urn)
        if dp is None:
            nodes.append({"urn": urn, "name": urn.split(":")[3] if len(urn.split(":")) > 3 else urn,
                          "title": urn, "domain": "external", "lifecycle": "unknown", "external": True,
                          "isRoot": False})
            continue
        nodes.append(
            {
                "urn": dp.urn,
                "name": dp.name,
                "title": dp.title,
                "domain": dp.domain.name,
                "lifecycle": str(dp.lifecycle),
                "outputPorts": sum(1 for c in dp.components if c.kind == ComponentKind.OUTPUT_PORT),
                "external": False,
                "isRoot": root is not None and dp.id == root.id,
            }
        )

    graph_edges = []
    for edge in edges:
        source_urn = id_to_urn.get(edge.source_dp_id)
        if source_urn not in included or edge.target_dp_urn not in included:
            continue
        graph_edges.append(
            {
                "source": edge.target_dp_urn,  # data flows producer -> consumer
                "target": source_urn,
                "port": edge.target_port_urn,
                "resolved": edge.resolved,
            }
        )
    return {"nodes": nodes, "edges": graph_edges}
