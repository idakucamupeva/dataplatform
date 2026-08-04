"""Producer-facing API: the builder experience."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, TargetDataProduct, assert_can_edit, assert_can_govern
from app.api.serializers import (
    commit_out,
    component_out,
    data_product_out,
    deployment_out,
    event_out,
    policy_evaluation_out,
    version_out,
)
from app.core.config import settings
from app.models import (
    DataProduct,
    DataProductVersion,
    Deployment,
    Domain,
    Event,
    LifecycleState,
    LineageEdge,
    PolicyEvaluation,
)
from app.provisioners import registry as provisioner_registry
from app.services import dataproducts, provisioning
from app.services.marketplace import lineage_graph
from app.services.repository import repository_service

router = APIRouter(prefix="/dataproducts", tags=["data products"])


# --------------------------------------------------------------------------
# request bodies
# --------------------------------------------------------------------------
class ScaffoldRequest(BaseModel):
    template_id: str = Field(alias="templateId")
    values: dict[str, Any] = Field(default_factory=dict)
    model_config = {"populate_by_name": True}


class DescriptorUpdate(BaseModel):
    content: str
    message: str = "chore: update descriptor"


class AddComponentRequest(BaseModel):
    template_id: str = Field(alias="templateId")
    values: dict[str, Any] = Field(default_factory=dict)
    model_config = {"populate_by_name": True}


class DependencyRequest(BaseModel):
    port_urn: str = Field(alias="portUrn")
    model_config = {"populate_by_name": True}


class ReleaseRequest(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    notes: str = ""


class DeployRequest(BaseModel):
    environment: str
    version_id: int | None = Field(default=None, alias="versionId")
    model_config = {"populate_by_name": True}


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------
@router.get("")
def list_data_products(
    db: DbSession,
    user: CurrentUser,
    scope: Literal["all", "mine"] = "all",
    domain: str | None = None,
    lifecycle: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = select(DataProduct)
    if scope == "mine":
        stmt = stmt.where(DataProduct.owner_id == user.id)
    if domain:
        stmt = stmt.join(Domain, DataProduct.domain_id == Domain.id).where(Domain.name == domain)
    if lifecycle:
        stmt = stmt.where(DataProduct.lifecycle == lifecycle)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(DataProduct.title.ilike(like) | DataProduct.name.ilike(like))
    products = db.execute(stmt.order_by(DataProduct.updated_at.desc())).scalars().unique()
    return [
        data_product_out(dp, extra={"environments": provisioning.environment_status(db, dp)})
        for dp in products
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_data_product(payload: ScaffoldRequest, db: DbSession, user: CurrentUser) -> dict:
    dp = dataproducts.scaffold(db, template_id=payload.template_id, values=payload.values, owner=user)
    return data_product_out(dp, extra={"environments": provisioning.environment_status(db, dp)})


# --------------------------------------------------------------------------
# single data product
# --------------------------------------------------------------------------
@router.get("/{dp_id}")
def get_data_product(dp: TargetDataProduct, db: DbSession, user: CurrentUser) -> dict:
    latest_policy = db.execute(
        select(PolicyEvaluation)
        .where(PolicyEvaluation.data_product_id == dp.id)
        .order_by(PolicyEvaluation.id.desc())
    ).scalars().first()
    return data_product_out(
        dp,
        extra={
            "components": [component_out(c) for c in dp.components],
            "environments": provisioning.environment_status(db, dp),
            "versions": [version_out(v) for v in dp.versions],
            "policy": policy_evaluation_out(latest_policy) if latest_policy else None,
            "dependencies": [
                {"portUrn": e.target_port_urn, "dataProductUrn": e.target_dp_urn, "resolved": e.resolved}
                for e in _dependencies(db, dp)
            ],
            "canEdit": dp.owner_id == user.id or user.is_admin(),
            "gateEnvironment": settings.marketplace_gate_environment,
        },
    )


def _dependencies(db, dp: DataProduct) -> list[LineageEdge]:
    return list(db.execute(select(LineageEdge).where(LineageEdge.source_dp_id == dp.id)).scalars())


@router.delete("/{dp_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_data_product(dp: TargetDataProduct, db: DbSession, user: CurrentUser) -> None:
    assert_can_edit(dp, user)
    if dp.lifecycle == LifecycleState.PUBLISHED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A published data product cannot be deleted; retire it first so consumers are warned",
        )
    slug = dataproducts.repo_slug(dp)
    db.delete(dp)
    db.flush()
    repository_service.destroy(slug)


# --------------------------------------------------------------------------
# descriptor
# --------------------------------------------------------------------------
@router.get("/{dp_id}/descriptor")
def get_descriptor(dp: TargetDataProduct, _: CurrentUser, ref: str = "HEAD") -> dict:
    raw = dataproducts.read_descriptor_raw(dp, ref)
    return {"content": raw, "parsed": dataproducts.parse_descriptor(raw).to_dict(), "ref": ref}


@router.put("/{dp_id}/descriptor")
def update_descriptor(
    dp: TargetDataProduct, payload: DescriptorUpdate, db: DbSession, user: CurrentUser
) -> dict:
    assert_can_edit(dp, user)
    descriptor, report = dataproducts.save_descriptor(db, dp, payload.content, user, payload.message)
    return {
        "dataProduct": data_product_out(dp),
        "parsed": descriptor.to_dict(),
        "policy": report.as_dict(),
    }


# --------------------------------------------------------------------------
# components
# --------------------------------------------------------------------------
@router.post("/{dp_id}/components", status_code=status.HTTP_201_CREATED)
def add_component(
    dp: TargetDataProduct, payload: AddComponentRequest, db: DbSession, user: CurrentUser
) -> dict:
    assert_can_edit(dp, user)
    descriptor, report = dataproducts.add_component(
        db, dp, template_id=payload.template_id, values=payload.values, actor=user
    )
    return {
        "dataProduct": data_product_out(dp, extra={"components": [component_out(c) for c in dp.components]}),
        "policy": report.as_dict(),
    }


@router.delete("/{dp_id}/components/{component_name}", status_code=status.HTTP_204_NO_CONTENT)
def remove_component(
    dp: TargetDataProduct, component_name: str, db: DbSession, user: CurrentUser
) -> None:
    assert_can_edit(dp, user)
    dataproducts.remove_component(db, dp, component_name, user)


@router.post("/{dp_id}/dependencies", status_code=status.HTTP_201_CREATED)
def add_dependency(
    dp: TargetDataProduct, payload: DependencyRequest, db: DbSession, user: CurrentUser
) -> dict:
    assert_can_edit(dp, user)
    descriptor = dataproducts.add_dependency(db, dp, payload.port_urn, user)
    return {"dependsOn": descriptor.spec.depends_on}


# --------------------------------------------------------------------------
# governance
# --------------------------------------------------------------------------
@router.post("/{dp_id}/validate")
def validate(dp: TargetDataProduct, db: DbSession, _: CurrentUser) -> dict:
    report = dataproducts.run_policies(db, dp, trigger="manual")
    return report.as_dict()


@router.get("/{dp_id}/policy-history")
def policy_history(dp: TargetDataProduct, db: DbSession, _: CurrentUser, limit: int = 20) -> list[dict]:
    evaluations = db.execute(
        select(PolicyEvaluation)
        .where(PolicyEvaluation.data_product_id == dp.id)
        .order_by(PolicyEvaluation.id.desc())
        .limit(limit)
    ).scalars()
    return [policy_evaluation_out(e) for e in evaluations]


@router.post("/{dp_id}/submit")
def submit_for_review(dp: TargetDataProduct, db: DbSession, user: CurrentUser) -> dict:
    assert_can_edit(dp, user)
    report = dataproducts.submit_for_review(db, dp, user)
    return {"dataProduct": data_product_out(dp), "policy": report.as_dict()}


@router.post("/{dp_id}/release")
def release(dp: TargetDataProduct, payload: ReleaseRequest, db: DbSession, user: CurrentUser) -> dict:
    # A product under review is released by governance; a draft by its owner.
    if dp.lifecycle == LifecycleState.IN_REVIEW:
        assert_can_govern(user)
    else:
        assert_can_edit(dp, user)
    version = dataproducts.release(db, dp, version=payload.version, notes=payload.notes, actor=user)
    return {"dataProduct": data_product_out(dp), "version": version_out(version)}


@router.post("/{dp_id}/publish")
def publish(dp: TargetDataProduct, db: DbSession, user: CurrentUser) -> dict:
    assert_can_edit(dp, user)
    dataproducts.publish(db, dp, user)
    return data_product_out(dp)


@router.post("/{dp_id}/retire")
def retire(dp: TargetDataProduct, db: DbSession, user: CurrentUser, reason: str = "") -> dict:
    assert_can_edit(dp, user)
    dataproducts.retire(db, dp, user, reason)
    return data_product_out(dp)


# --------------------------------------------------------------------------
# repository
# --------------------------------------------------------------------------
@router.get("/{dp_id}/repository")
def repository(dp: TargetDataProduct, _: CurrentUser, limit: int = 30) -> dict:
    slug = dataproducts.repo_slug(dp)
    return {
        "slug": slug,
        "path": dp.repo_path,
        "files": repository_service.list_files(slug),
        "commits": [commit_out(c) for c in repository_service.log(slug, limit=limit)],
        "tags": repository_service.tags(slug),
    }


@router.get("/{dp_id}/repository/file")
def repository_file(dp: TargetDataProduct, _: CurrentUser, path: str, ref: str = "HEAD") -> dict:
    try:
        return {"path": path, "ref": ref, "content": repository_service.read(dataproducts.repo_slug(dp), path, ref)}
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/{dp_id}/repository/diff")
def repository_diff(
    dp: TargetDataProduct, _: CurrentUser, base: str, head: str = "HEAD", path: str | None = None
) -> dict:
    return {"diff": repository_service.diff(dataproducts.repo_slug(dp), base, head, path)}


@router.get("/{dp_id}/versions")
def versions(dp: TargetDataProduct, db: DbSession, _: CurrentUser) -> list[dict]:
    items = db.execute(
        select(DataProductVersion)
        .where(DataProductVersion.data_product_id == dp.id)
        .order_by(DataProductVersion.id.desc())
    ).scalars()
    return [version_out(v) for v in items]


@router.get("/{dp_id}/versions/{version_id}/descriptor")
def version_descriptor(dp: TargetDataProduct, version_id: int, db: DbSession, _: CurrentUser) -> dict:
    version = db.get(DataProductVersion, version_id)
    if version is None or version.data_product_id != dp.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return {"version": version.version, "content": version.descriptor_yaml}


# --------------------------------------------------------------------------
# deployments
# --------------------------------------------------------------------------
@router.get("/{dp_id}/deployments")
def list_deployments(dp: TargetDataProduct, db: DbSession, _: CurrentUser, limit: int = 20) -> list[dict]:
    items = db.execute(
        select(Deployment)
        .where(Deployment.data_product_id == dp.id)
        .order_by(Deployment.id.desc())
        .limit(limit)
    ).scalars()
    return [deployment_out(d) for d in items]


@router.get("/{dp_id}/deployments/{deployment_id}")
def get_deployment(dp: TargetDataProduct, deployment_id: int, db: DbSession, _: CurrentUser) -> dict:
    deployment = db.get(Deployment, deployment_id)
    if deployment is None or deployment.data_product_id != dp.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    return deployment_out(deployment, include_logs=True)


@router.post("/{dp_id}/deployments", status_code=status.HTTP_201_CREATED)
def deploy(dp: TargetDataProduct, payload: DeployRequest, db: DbSession, user: CurrentUser) -> dict:
    assert_can_edit(dp, user)
    version = None
    if payload.version_id is not None:
        version = db.get(DataProductVersion, payload.version_id)
        if version is None or version.data_product_id != dp.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    deployment = provisioning.deploy(db, dp, environment=payload.environment, actor=user, version=version)
    return deployment_out(deployment, include_logs=True)


@router.post("/{dp_id}/deployments/plan")
def deployment_plan(
    dp: TargetDataProduct,
    db: DbSession,
    _: CurrentUser,
    environment: str = Query(default="development"),
) -> dict:
    descriptor = dataproducts.read_descriptor(dp)
    steps = []
    for component in provisioning.plan(descriptor):
        provisioner = provisioner_registry.for_component(component)
        steps.append(
            {
                "component": component.name,
                "kind": str(component.kind),
                "technology": component.technology,
                "provisioner": provisioner.__class__.__name__ if provisioner else None,
                "platform": provisioner.platform if provisioner else "",
            }
        )
    return {"environment": environment, "steps": steps, "problems": provisioning.preflight(descriptor, environment)}


@router.delete("/{dp_id}/deployments", status_code=status.HTTP_200_OK)
def undeploy(dp: TargetDataProduct, db: DbSession, user: CurrentUser, environment: str) -> dict:
    assert_can_edit(dp, user)
    deployment = provisioning.undeploy(db, dp, environment=environment, actor=user)
    return deployment_out(deployment, include_logs=True)


# --------------------------------------------------------------------------
# activity
# --------------------------------------------------------------------------
@router.get("/{dp_id}/events")
def events(dp: TargetDataProduct, db: DbSession, _: CurrentUser, limit: int = 50) -> list[dict]:
    items = db.execute(
        select(Event).where(Event.data_product_id == dp.id).order_by(Event.id.desc()).limit(limit)
    ).scalars()
    return [event_out(e) for e in items]


@router.get("/{dp_id}/lineage")
def lineage(dp: TargetDataProduct, db: DbSession, _: CurrentUser, depth: int = 2) -> dict:
    return lineage_graph(db, dp, depth=depth)
