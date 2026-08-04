"""Consumer-facing API: discovery and access."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.serializers import access_request_out, component_out, data_product_out, user_out
from app.models import (
    AccessRequest,
    AccessRequestStatus,
    Component,
    ComponentKind,
    DataProduct,
    DataProductVersion,
    LifecycleState,
)
from app.services import marketplace, provisioning

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


class AccessRequestBody(BaseModel):
    component_id: int | None = Field(default=None, alias="componentId")
    purpose: str = Field(min_length=10)
    consumer_data_product: str = Field(default="", alias="consumerDataProduct")
    model_config = {"populate_by_name": True}


class DecisionBody(BaseModel):
    approve: bool
    note: str = ""


@router.get("")
def browse(
    db: DbSession,
    _: CurrentUser,
    q: str = "",
    domain: str | None = None,
    tag: str | None = None,
    technology: str | None = None,
) -> dict:
    products = marketplace.search(db, query=q, domain=domain, tag=tag, technology=technology)
    return {
        "items": [
            data_product_out(
                dp,
                extra={
                    "outputPorts": [
                        component_out(c, include_spec=False)
                        for c in dp.components
                        if c.kind == ComponentKind.OUTPUT_PORT
                    ]
                },
            )
            for dp in products
        ],
        "facets": marketplace.facets(db),
        "total": len(products),
    }


@router.get("/{dp_id}")
def detail(dp_id: int, db: DbSession, user: CurrentUser) -> dict:
    dp = db.get(DataProduct, dp_id)
    if dp is None or dp.lifecycle != LifecycleState.PUBLISHED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not available in the marketplace")

    released = db.execute(
        select(DataProductVersion)
        .where(DataProductVersion.data_product_id == dp.id)
        .order_by(DataProductVersion.id.desc())
    ).scalars().first()

    my_requests = db.execute(
        select(AccessRequest).where(
            AccessRequest.data_product_id == dp.id, AccessRequest.requester_id == user.id
        )
    ).scalars().all()

    ports = [c for c in dp.components if c.kind == ComponentKind.OUTPUT_PORT]
    return data_product_out(
        dp,
        extra={
            "outputPorts": [
                {
                    **component_out(port),
                    "access": _access_state(port, my_requests, dp, user),
                }
                for port in ports
            ],
            "internalComponents": [
                component_out(c, include_spec=False) for c in dp.components if c.kind != ComponentKind.OUTPUT_PORT
            ],
            "releasedVersion": released.version if released else dp.version,
            "environments": provisioning.environment_status(db, dp),
            "myRequests": [access_request_out(r) for r in my_requests],
            "isOwner": dp.owner_id == user.id,
        },
    )


def _access_state(port: Component, requests: list[AccessRequest], dp: DataProduct, user) -> str:
    if dp.owner_id == user.id:
        return "owner"
    for request in requests:
        if request.component_id == port.id and request.status in (
            AccessRequestStatus.PENDING,
            AccessRequestStatus.APPROVED,
        ):
            return str(request.status)
    return "none"


@router.post("/{dp_id}/access-requests", status_code=status.HTTP_201_CREATED)
def request_access(dp_id: int, payload: AccessRequestBody, db: DbSession, user: CurrentUser) -> dict:
    dp = db.get(DataProduct, dp_id)
    if dp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Data product not found")
    component = None
    if payload.component_id is not None:
        component = db.get(Component, payload.component_id)
        if component is None or component.data_product_id != dp.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Output port not found on this data product")
    request = marketplace.request_access(
        db,
        dp=dp,
        component=component,
        requester=user,
        purpose=payload.purpose,
        consumer_dp_urn=payload.consumer_data_product,
    )
    return access_request_out(request)


@router.get("/access-requests/inbox")
def inbox(db: DbSession, user: CurrentUser) -> list[dict]:
    """Requests waiting for *my* decision, as the owner of the data product."""
    stmt = (
        select(AccessRequest)
        .join(DataProduct, AccessRequest.data_product_id == DataProduct.id)
        .order_by(AccessRequest.created_at.desc())
    )
    if not user.can_govern():
        stmt = stmt.where(DataProduct.owner_id == user.id)
    return [access_request_out(r) for r in db.execute(stmt).scalars().unique()]


@router.get("/access-requests/outbox")
def outbox(db: DbSession, user: CurrentUser) -> list[dict]:
    items = db.execute(
        select(AccessRequest)
        .where(AccessRequest.requester_id == user.id)
        .order_by(AccessRequest.created_at.desc())
    ).scalars()
    return [access_request_out(r) for r in items]


@router.post("/access-requests/{request_id}/decision")
def decide(request_id: int, payload: DecisionBody, db: DbSession, user: CurrentUser) -> dict:
    request = db.get(AccessRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Access request not found")
    if request.data_product.owner_id != user.id and not user.can_govern():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the owning domain can decide on this request"
        )
    marketplace.decide(db, request, approve=payload.approve, decider=user, note=payload.note)
    return access_request_out(request)


@router.post("/access-requests/{request_id}/revoke")
def revoke(request_id: int, db: DbSession, user: CurrentUser, note: str = "") -> dict:
    request = db.get(AccessRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Access request not found")
    if request.data_product.owner_id != user.id and not user.can_govern():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owning domain can revoke this access")
    marketplace.revoke(db, request, actor=user, note=note)
    return access_request_out(request)


@router.get("/me/subscriptions")
def subscriptions(db: DbSession, user: CurrentUser) -> list[dict]:
    return [access_request_out(r) for r in marketplace.granted_ports(db, user)]


@router.get("/output-ports/published")
def published_ports(db: DbSession, _: CurrentUser, q: str = "") -> list[dict]:
    """Every consumable output port — used when declaring a dependency."""
    stmt = (
        select(Component)
        .join(DataProduct, Component.data_product_id == DataProduct.id)
        .where(Component.kind == ComponentKind.OUTPUT_PORT)
        .where(DataProduct.lifecycle == LifecycleState.PUBLISHED)
    )
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(Component.urn.ilike(like) | Component.title.ilike(like))
    return [
        {
            **component_out(component, include_spec=False),
            "dataProduct": {
                "id": component.data_product.id,
                "urn": component.data_product.urn,
                "title": component.data_product.title,
                "domain": component.data_product.domain.name,
                "owner": user_out(component.data_product.owner),
            },
        }
        for component in db.execute(stmt).scalars().unique()
    ]
