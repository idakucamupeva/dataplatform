"""Platform-level endpoints: domains, governance policies, activity, metrics."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.serializers import domain_out, event_out, user_out
from app.core.config import settings
from app.models import (
    AccessRequest,
    AccessRequestStatus,
    Component,
    ComponentKind,
    DataProduct,
    Deployment,
    DeploymentStatus,
    Domain,
    Event,
    LifecycleState,
    User,
)
from app.provisioners import registry as provisioner_registry
from app.services.github import GitHubError, get_client as get_github_client
from app.services.marketplace import lineage_graph
from app.services.policies import POLICIES

router = APIRouter(tags=["platform"])


class DomainBody(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])$")
    title: str = ""
    description: str = ""
    owner_id: int | None = Field(default=None, alias="ownerId")
    model_config = {"populate_by_name": True}


@router.get("/platform/info")
def platform_info(_: CurrentUser) -> dict:
    return {
        "name": settings.platform_name,
        "urnNamespace": settings.urn_namespace,
        "environments": settings.environments,
        "marketplaceGateEnvironment": settings.marketplace_gate_environment,
        "provisioners": [
            {"technology": p.technology, "platform": p.platform, "requiredKeys": list(p.required_keys)}
            for p in provisioner_registry.all()
        ],
        # no network call here — just whether a token is configured
        "github": {
            "enabled": get_github_client() is not None,
            "owner": settings.github_owner or None,
            "repoPrefix": settings.github_repo_prefix,
        },
    }


@router.get("/platform/github/status")
def github_status(_: CurrentUser) -> dict:
    """Live check of the configured GitHub token (one API call)."""
    client = get_github_client()
    if client is None:
        return {
            "enabled": False,
            "ok": False,
            "message": "Local mode — set DMP_GITHUB_TOKEN to create data product repositories on GitHub.",
        }
    try:
        return {"enabled": True, "ok": True, **client.status()}
    except GitHubError as exc:
        return {"enabled": True, "ok": False, "error": str(exc)}


@router.get("/policies")
def list_policies(_: CurrentUser) -> list[dict]:
    return [p.as_dict() for p in POLICIES]


# --------------------------------------------------------------------------
# domains
# --------------------------------------------------------------------------
@router.get("/domains")
def list_domains(db: DbSession, _: CurrentUser) -> list[dict]:
    return [domain_out(d) for d in db.execute(select(Domain).order_by(Domain.name)).scalars().unique()]


@router.post("/domains", status_code=status.HTTP_201_CREATED)
def create_domain(payload: DomainBody, db: DbSession, _: AdminUser) -> dict:
    if db.execute(select(Domain).where(Domain.name == payload.name)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Domain '{payload.name}' already exists")
    domain = Domain(
        name=payload.name,
        title=payload.title or payload.name.replace("-", " ").title(),
        description=payload.description,
        owner_id=payload.owner_id,
    )
    db.add(domain)
    db.flush()
    return domain_out(domain)


@router.put("/domains/{domain_id}")
def update_domain(domain_id: int, payload: DomainBody, db: DbSession, _: AdminUser) -> dict:
    domain = db.get(Domain, domain_id)
    if domain is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain not found")
    domain.title = payload.title or domain.title
    domain.description = payload.description
    domain.owner_id = payload.owner_id
    db.flush()
    return domain_out(domain)


# --------------------------------------------------------------------------
# activity & lineage
# --------------------------------------------------------------------------
@router.get("/events")
def events(db: DbSession, _: CurrentUser, limit: int = 40) -> list[dict]:
    items = db.execute(select(Event).order_by(Event.id.desc()).limit(limit)).scalars().unique()
    return [event_out(e) for e in items]


@router.get("/lineage")
def mesh_lineage(db: DbSession, _: CurrentUser) -> dict:
    return lineage_graph(db)


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
@router.get("/metrics")
def metrics(db: DbSession, user: CurrentUser) -> dict:
    def count(stmt) -> int:
        return db.execute(stmt).scalar_one()

    by_lifecycle = {
        str(state): count(
            select(func.count(DataProduct.id)).where(DataProduct.lifecycle == state)
        )
        for state in LifecycleState
    }
    by_domain = [
        {"domain": name, "count": total}
        for name, total in db.execute(
            select(Domain.name, func.count(DataProduct.id))
            .join(DataProduct, DataProduct.domain_id == Domain.id)
            .group_by(Domain.name)
            .order_by(func.count(DataProduct.id).desc())
        ).all()
    ]
    by_technology = [
        {"technology": tech or "unknown", "count": total}
        for tech, total in db.execute(
            select(Component.technology, func.count(Component.id))
            .where(Component.kind == ComponentKind.OUTPUT_PORT)
            .group_by(Component.technology)
            .order_by(func.count(Component.id).desc())
        ).all()
    ]
    environments = [
        {
            "environment": environment,
            "provisioned": count(
                select(func.count(func.distinct(Deployment.data_product_id))).where(
                    Deployment.environment == environment,
                    Deployment.status == DeploymentStatus.PROVISIONED,
                )
            ),
        }
        for environment in settings.environments
    ]
    return {
        "dataProducts": count(select(func.count(DataProduct.id))),
        "published": by_lifecycle.get(str(LifecycleState.PUBLISHED), 0),
        "components": count(select(func.count(Component.id))),
        "outputPorts": count(
            select(func.count(Component.id)).where(Component.kind == ComponentKind.OUTPUT_PORT)
        ),
        "domains": count(select(func.count(Domain.id))),
        "users": count(select(func.count(User.id))),
        "myDataProducts": count(
            select(func.count(DataProduct.id)).where(DataProduct.owner_id == user.id)
        ),
        "pendingAccessRequests": count(
            select(func.count(AccessRequest.id))
            .join(DataProduct, AccessRequest.data_product_id == DataProduct.id)
            .where(
                AccessRequest.status == AccessRequestStatus.PENDING,
                DataProduct.owner_id == user.id,
            )
        ),
        "byLifecycle": by_lifecycle,
        "byDomain": by_domain,
        "byTechnology": by_technology,
        "environments": environments,
    }


@router.get("/governance/queue")
def governance_queue(db: DbSession, user: CurrentUser) -> list[dict]:
    """Data products waiting for a federated governance decision."""
    from app.api.serializers import data_product_out

    if not user.can_govern():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Governance role required")
    items = db.execute(
        select(DataProduct)
        .where(DataProduct.lifecycle == LifecycleState.IN_REVIEW)
        .order_by(DataProduct.updated_at)
    ).scalars().unique()
    return [data_product_out(dp) for dp in items]


@router.get("/users")
def users(db: DbSession, _: CurrentUser) -> list[dict]:
    return [user_out(u) for u in db.execute(select(User).order_by(User.username)).scalars()]
