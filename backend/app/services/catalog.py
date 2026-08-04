"""Projection of descriptors into the queryable catalog.

`ingest` is the single place where a descriptor becomes rows.  Nothing else in
the platform writes to the `components` or `lineage_edges` tables — which is
what keeps the database honest about being a derived read model.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Component, DataProduct, Domain, Event, LifecycleState, LineageEdge, User
from app.schemas.descriptor import Descriptor
from app.services.urns import data_product_urn, parse_urn


def record_event(
    db: Session,
    *,
    type_: str,
    message: str,
    actor: User | None = None,
    data_product: DataProduct | None = None,
    payload: dict | None = None,
) -> Event:
    event = Event(
        type=type_,
        message=message,
        actor_id=actor.id if actor else None,
        data_product_id=data_product.id if data_product else None,
        payload=payload or {},
    )
    db.add(event)
    return event


def resolve_output_port(db: Session, urn: str) -> Component | None:
    """Find a *published* output port by URN. Used by policies and lineage."""
    parsed = parse_urn(urn)
    if parsed is None or not parsed.is_component:
        return None
    stmt = (
        select(Component)
        .join(DataProduct, Component.data_product_id == DataProduct.id)
        .where(Component.urn == urn)
        .where(DataProduct.lifecycle == LifecycleState.PUBLISHED)
    )
    return db.execute(stmt).scalars().first()


def dependency_resolver(db: Session):
    def resolve(urn: str) -> str | None:
        component = resolve_output_port(db, urn)
        return component.title or component.name if component else None

    return resolve


def ingest(db: Session, dp: DataProduct, descriptor: Descriptor, commit_sha: str = "") -> DataProduct:
    """Rebuild the catalog rows for `dp` from its descriptor."""
    meta = descriptor.metadata

    domain = db.execute(select(Domain).where(Domain.name == meta.domain)).scalars().first()
    if domain is None:
        domain = Domain(name=meta.domain, title=meta.domain.replace("-", " ").title())
        db.add(domain)
        db.flush()

    dp.urn = data_product_urn(meta.domain, meta.name, meta.version)
    dp.name = meta.name
    dp.title = meta.display_name or meta.name
    dp.description = meta.description
    dp.domain_id = domain.id
    dp.version = meta.version
    dp.maturity = meta.maturity
    dp.tags = list(meta.tags)
    if commit_sha:
        dp.head_commit = commit_sha

    # -- components ------------------------------------------------------
    existing = {c.name: c for c in dp.components}
    seen: set[str] = set()
    for spec in descriptor.spec.components:
        seen.add(spec.name)
        component = existing.get(spec.name) or Component(data_product_id=dp.id, name=spec.name)
        component.urn = spec.id or f"{dp.urn}:{spec.name}"
        component.title = spec.display_name or spec.name
        component.kind = spec.kind
        component.technology = spec.technology
        component.description = spec.description
        component.use_case_template_id = spec.use_case_template_id
        component.spec = spec.model_dump(by_alias=True, exclude_none=True, mode="json")
        if component.id is None:
            dp.components.append(component)
        db.add(component)
    for name, component in existing.items():
        if name not in seen:
            db.delete(component)

    # -- lineage ---------------------------------------------------------
    db.query(LineageEdge).filter(LineageEdge.source_dp_id == dp.id).delete(synchronize_session=False)
    dependencies = list(descriptor.spec.depends_on)
    for spec in descriptor.spec.components:
        dependencies.extend(spec.depends_on)
    own_prefix = dp.urn + ":"
    for urn in dict.fromkeys(dependencies):
        if not urn.startswith("urn:") or urn.startswith(own_prefix):
            continue
        parsed = parse_urn(urn)
        db.add(
            LineageEdge(
                source_dp_id=dp.id,
                target_port_urn=urn,
                target_dp_urn=parsed.data_product_urn if parsed else urn,
                resolved=resolve_output_port(db, urn) is not None,
            )
        )

    db.flush()
    return dp


def refresh_unresolved_edges(db: Session) -> None:
    """After a publish, previously dangling dependencies may now resolve."""
    for edge in db.execute(select(LineageEdge).where(LineageEdge.resolved.is_(False))).scalars():
        edge.resolved = resolve_output_port(db, edge.target_port_urn) is not None
    db.flush()
