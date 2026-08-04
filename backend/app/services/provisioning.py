"""The provisioning coordinator.

Given a data product version and a target environment it

1. re-runs the governance policies as a hard gate (for non-development
   environments),
2. resolves every component to a provisioner and validates it *before*
   touching anything,
3. executes the components in dependency order — storage, then workloads,
   then output ports, then observability — and
4. records a full log and the produced resource identifiers on the deployment.

Steps 2 and 3 are separated on purpose: a deployment that would fail halfway
is rejected before it starts, which is what makes re-running it safe.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    ComponentKind,
    DataProduct,
    DataProductVersion,
    Deployment,
    DeploymentStatus,
    LifecycleState,
    User,
)
from app.provisioners import registry
from app.schemas.descriptor import Component, Descriptor
from app.services import catalog, dataproducts

# storage first (workloads write into it), output ports once data can exist,
# observability last so it can reference everything else.
KIND_ORDER = {
    ComponentKind.STORAGE: 0,
    ComponentKind.WORKLOAD: 1,
    ComponentKind.OUTPUT_PORT: 2,
    ComponentKind.OBSERVABILITY: 3,
}


class ProvisioningError(Exception):
    def __init__(self, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


def plan(descriptor: Descriptor) -> list[Component]:
    """Deterministic execution order for the components of a descriptor."""
    return sorted(
        descriptor.spec.components,
        key=lambda c: (KIND_ORDER.get(c.kind, 99), c.name),
    )


def preflight(descriptor: Descriptor, environment: str) -> list[str]:
    """Everything that would make the run fail, collected up front."""
    problems: list[str] = []
    for component in plan(descriptor):
        provisioner = registry.for_component(component)
        if provisioner is None:
            problems.append(
                f"no provisioner is registered for technology '{component.technology}' "
                f"(component '{component.name}')"
            )
            continue
        problems.extend(
            f"{component.name}: {issue}"
            for issue in provisioner.validate(component, descriptor, environment)
        )
    return problems


def deploy(
    db: Session,
    dp: DataProduct,
    *,
    environment: str,
    actor: User,
    version: DataProductVersion | None = None,
) -> Deployment:
    if environment not in settings.environments:
        raise ProvisioningError(f"unknown environment '{environment}'")

    # Released versions deploy from their immutable snapshot; a draft deploys
    # from the working descriptor, but only into development.
    if version is not None:
        descriptor = dataproducts.parse_descriptor(version.descriptor_yaml)
        version_label = version.version
    else:
        latest = _latest_version(db, dp)
        if latest is not None and environment != "development":
            descriptor = dataproducts.parse_descriptor(latest.descriptor_yaml)
            version, version_label = latest, latest.version
        else:
            if environment != "development" and dp.lifecycle == LifecycleState.DRAFT:
                raise ProvisioningError(
                    f"'{environment}' only accepts released versions; release the data product first"
                )
            descriptor = dataproducts.read_descriptor(dp)
            version_label = f"{descriptor.metadata.version}+draft"

    if environment != "development":
        report = dataproducts.run_policies(db, dp, descriptor, trigger="deploy")
        if not report.passed:
            raise ProvisioningError(
                f"governance blocks deployment to {environment}",
                [f.message for f in report.errors],
            )

    problems = preflight(descriptor, environment)
    if problems:
        raise ProvisioningError(f"the deployment plan is not valid for {environment}", problems)

    deployment = Deployment(
        data_product_id=dp.id,
        version_id=version.id if version else None,
        version_label=version_label,
        environment=environment,
        status=DeploymentStatus.PROVISIONING,
        operation="provision",
        requested_by_id=actor.id,
        logs=[],
        outputs={},
    )
    db.add(deployment)
    db.flush()

    logs: list[str] = [
        f"provisioning {dp.urn} version {version_label} into {environment}",
        f"{len(descriptor.spec.components)} component(s) in plan: "
        + ", ".join(f"{c.name} ({c.kind})" for c in plan(descriptor)),
    ]
    outputs: dict[str, dict] = {}
    failed: str | None = None

    for component in plan(descriptor):
        provisioner = registry.for_component(component)
        assert provisioner is not None  # guaranteed by preflight
        logs.append(f"--- {component.name} [{component.technology}] ---")
        try:
            result = provisioner.provision(component, descriptor, environment)
        except Exception as exc:  # pragma: no cover - adapter defect
            result = None
            failed = f"{component.name}: unexpected provisioner error: {exc}"
            logs.append(f"!! {failed}")
            break
        logs.extend(result.logs)
        if not result.ok:
            failed = f"{component.name}: {result.error}"
            logs.append(f"!! {failed}")
            break
        outputs[component.name] = result.outputs

    deployment.logs = logs
    deployment.outputs = outputs
    deployment.finished_at = datetime.now(timezone.utc)
    if failed:
        deployment.status = DeploymentStatus.FAILED
        logs.append(f"deployment failed: {failed}")
    else:
        deployment.status = DeploymentStatus.PROVISIONED
        logs.append(f"deployment completed: {len(outputs)} component(s) provisioned")
    db.flush()

    catalog.record_event(
        db,
        type_="deployment.finished",
        message=f"Provisioning of {version_label} into {environment} "
        + ("failed" if failed else "succeeded"),
        actor=actor,
        data_product=dp,
        payload={"environment": environment, "status": str(deployment.status), "version": version_label},
    )
    return deployment


def undeploy(db: Session, dp: DataProduct, *, environment: str, actor: User) -> Deployment:
    previous = latest_deployment(db, dp, environment)
    if previous is None or previous.status != DeploymentStatus.PROVISIONED:
        raise ProvisioningError(f"{dp.name} is not provisioned in {environment}")

    descriptor = (
        dataproducts.parse_descriptor(previous.version.descriptor_yaml)
        if previous.version
        else dataproducts.read_descriptor(dp)
    )
    logs = [f"destroying {dp.urn} in {environment}"]
    for component in reversed(plan(descriptor)):
        provisioner = registry.for_component(component)
        if provisioner is None:
            continue
        logs.extend(provisioner.destroy(component, descriptor, environment).logs)

    deployment = Deployment(
        data_product_id=dp.id,
        version_id=previous.version_id,
        version_label=previous.version_label,
        environment=environment,
        status=DeploymentStatus.DESTROYED,
        operation="destroy",
        requested_by_id=actor.id,
        logs=logs + ["all resources removed"],
        outputs={},
        finished_at=datetime.now(timezone.utc),
    )
    db.add(deployment)
    db.flush()
    catalog.record_event(
        db, type_="deployment.destroyed", message=f"Removed from {environment}",
        actor=actor, data_product=dp, payload={"environment": environment},
    )
    return deployment


def latest_deployment(db: Session, dp: DataProduct, environment: str) -> Deployment | None:
    return db.execute(
        select(Deployment)
        .where(Deployment.data_product_id == dp.id, Deployment.environment == environment)
        .order_by(Deployment.id.desc())
    ).scalars().first()


def environment_status(db: Session, dp: DataProduct) -> list[dict]:
    out = []
    for environment in settings.environments:
        deployment = latest_deployment(db, dp, environment)
        out.append(
            {
                "environment": environment,
                "status": str(deployment.status) if deployment else str(DeploymentStatus.NOT_DEPLOYED),
                "version": deployment.version_label if deployment else None,
                "deployedAt": deployment.finished_at if deployment else None,
                "deploymentId": deployment.id if deployment else None,
            }
        )
    return out


def _latest_version(db: Session, dp: DataProduct) -> DataProductVersion | None:
    return db.execute(
        select(DataProductVersion)
        .where(DataProductVersion.data_product_id == dp.id)
        .order_by(DataProductVersion.id.desc())
    ).scalars().first()
