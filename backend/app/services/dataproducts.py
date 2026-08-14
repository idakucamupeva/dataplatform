"""The data product lifecycle.

Scaffold -> edit (add components / edit the descriptor) -> validate -> release
-> provision -> publish.  Every step that changes metadata goes through the
repository first and the catalog second, so the descriptor in git is never
behind what the platform believes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DataProduct,
    DataProductVersion,
    Domain,
    LifecycleState,
    PolicyEvaluation,
    User,
)
from app.schemas.descriptor import Component as ComponentSpec
from app.schemas.descriptor import Descriptor
from app.services import catalog
from app.services.descriptor_io import DescriptorError, parse_descriptor, serialize
from app.services.policies import PolicyContext, PolicyReport, evaluate
from app.services.repository import repository_service
from app.services.templates import TemplateError_, render_node, template_registry
from app.services.urns import data_product_urn

DESCRIPTOR_PATH = "data-product-descriptor.yaml"


class LifecycleError(Exception):
    """A transition the current state does not allow."""


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------
def repo_slug(dp: DataProduct) -> str:
    return repository_service.slug(dp.domain.name, dp.name)


def read_descriptor(dp: DataProduct, ref: str = "HEAD") -> Descriptor:
    raw = repository_service.read(repo_slug(dp), dp.descriptor_path or DESCRIPTOR_PATH, ref)
    return parse_descriptor(raw)


def read_descriptor_raw(dp: DataProduct, ref: str = "HEAD") -> str:
    return repository_service.read(repo_slug(dp), dp.descriptor_path or DESCRIPTOR_PATH, ref)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
def run_policies(
    db: Session,
    dp: DataProduct,
    descriptor: Descriptor | None = None,
    *,
    trigger: str = "manual",
    persist: bool = True,
) -> PolicyReport:
    descriptor = descriptor or read_descriptor(dp)
    report = evaluate(PolicyContext(descriptor=descriptor, resolve_dependency=catalog.dependency_resolver(db)))
    if persist:
        db.add(
            PolicyEvaluation(
                data_product_id=dp.id,
                trigger=trigger,
                passed=report.passed,
                error_count=len(report.errors),
                warning_count=len(report.warnings),
                results=[f.as_dict() for f in report.findings],
            )
        )
        db.flush()
    return report


# --------------------------------------------------------------------------
# creation
# --------------------------------------------------------------------------
def scaffold(db: Session, *, template_id: str, values: dict[str, Any], owner: User) -> DataProduct:
    template = template_registry.get(template_id)
    if template.type != "dataproduct":
        raise TemplateError_(f"template '{template_id}' does not create a data product")

    resolved = template_registry.validate_values(template, values)
    domain_name = str(resolved.get("domain", "")).strip()
    domain = db.execute(select(Domain).where(Domain.name == domain_name)).scalars().first()
    if domain is None:
        raise LifecycleError(f"unknown domain '{domain_name}'")

    ctx = {**resolved, "__owner__": owner.username, "__owner_name__": owner.display_name}
    descriptor_doc = render_node(template.descriptor or {}, ctx)
    try:
        descriptor = Descriptor.model_validate(descriptor_doc)
    except Exception as exc:  # pragma: no cover - template authoring error
        raise DescriptorError(f"template '{template_id}' produced an invalid descriptor: {exc}") from exc

    name = descriptor.metadata.name
    urn = data_product_urn(domain.name, name, descriptor.metadata.version)
    if db.execute(select(DataProduct).where(DataProduct.urn == urn)).scalars().first():
        raise LifecycleError(f"a data product with URN {urn} already exists")

    slug = repository_service.slug(domain.name, name)
    if repository_service.exists(slug):
        raise LifecycleError(f"repository '{slug}' already exists")

    files = {DESCRIPTOR_PATH: serialize(descriptor)}
    files.update(template_registry.render_files(template, ctx))

    commit = repository_service.create(
        slug,
        files,
        author=owner.display_name,
        email=owner.email,
        message=f"feat: scaffold data product {name} from template {template_id}",
        description=f"[{domain.name}] {descriptor.metadata.description}",
    )

    dp = DataProduct(
        urn=urn,
        name=name,
        title=descriptor.metadata.display_name,
        description=descriptor.metadata.description,
        domain_id=domain.id,
        owner_id=owner.id,
        lifecycle=LifecycleState.DRAFT,
        version=descriptor.metadata.version,
        maturity=descriptor.metadata.maturity,
        tags=list(descriptor.metadata.tags),
        repo_path=repository_service.remote_display(slug),
        descriptor_path=DESCRIPTOR_PATH,
        head_commit=commit,
    )
    db.add(dp)
    db.flush()
    db.refresh(dp)

    catalog.ingest(db, dp, descriptor, commit)
    catalog.record_event(
        db,
        type_="dataproduct.created",
        message=f"Scaffolded '{dp.title}' from template '{template.name}'",
        actor=owner,
        data_product=dp,
        payload={"templateId": template_id, "commit": commit},
    )
    run_policies(db, dp, descriptor, trigger="save")
    return dp


# --------------------------------------------------------------------------
# editing
# --------------------------------------------------------------------------
def save_descriptor(
    db: Session, dp: DataProduct, raw_yaml: str, actor: User, message: str = "chore: update descriptor"
) -> tuple[Descriptor, PolicyReport]:
    _require_editable(dp)
    descriptor = parse_descriptor(raw_yaml)
    if descriptor.metadata.name != dp.name:
        raise LifecycleError("the data product name is immutable; create a new data product instead")
    if descriptor.metadata.domain != dp.domain.name:
        raise LifecycleError("the domain is immutable once the repository exists")

    commit = repository_service.commit(
        repo_slug(dp),
        {dp.descriptor_path or DESCRIPTOR_PATH: serialize(descriptor)},
        author=actor.display_name,
        email=actor.email,
        message=message,
    )
    catalog.ingest(db, dp, descriptor, commit)
    catalog.record_event(
        db, type_="descriptor.updated", message=message, actor=actor, data_product=dp,
        payload={"commit": commit},
    )
    report = run_policies(db, dp, descriptor, trigger="save")
    return descriptor, report


def add_component(
    db: Session, dp: DataProduct, *, template_id: str, values: dict[str, Any], actor: User
) -> tuple[Descriptor, PolicyReport]:
    """Render a component template and merge it into the descriptor."""
    _require_editable(dp)
    template = template_registry.get(template_id)
    if template.type != "component":
        raise TemplateError_(f"template '{template_id}' does not create a component")

    resolved = template_registry.validate_values(template, values)
    descriptor = read_descriptor(dp)
    ctx = {
        **resolved,
        "__owner__": dp.owner.username,
        "__domain__": dp.domain.name,
        "__data_product__": dp.name,
    }
    component_doc = render_node(template.component or {}, ctx)
    component = ComponentSpec.model_validate(component_doc)
    if descriptor.component(component.name) is not None:
        raise LifecycleError(f"component '{component.name}' already exists in this data product")

    descriptor.spec.components.append(component)
    files = {DESCRIPTOR_PATH: serialize(descriptor)}
    files.update(template_registry.render_files(template, ctx))

    commit = repository_service.commit(
        repo_slug(dp),
        files,
        author=actor.display_name,
        email=actor.email,
        message=f"feat: add {component.kind} component '{component.name}' ({template.name})",
    )
    catalog.ingest(db, dp, descriptor, commit)
    catalog.record_event(
        db,
        type_="component.added",
        message=f"Added {component.kind} '{component.display_name or component.name}'",
        actor=actor,
        data_product=dp,
        payload={"component": component.name, "templateId": template_id, "commit": commit},
    )
    report = run_policies(db, dp, descriptor, trigger="save")
    return descriptor, report


def remove_component(db: Session, dp: DataProduct, component_name: str, actor: User) -> Descriptor:
    _require_editable(dp)
    descriptor = read_descriptor(dp)
    component = descriptor.component(component_name)
    if component is None:
        raise LifecycleError(f"no component named '{component_name}'")
    descriptor.spec.components = [c for c in descriptor.spec.components if c.name != component_name]

    commit = repository_service.commit(
        repo_slug(dp),
        {DESCRIPTOR_PATH: serialize(descriptor)},
        author=actor.display_name,
        email=actor.email,
        message=f"feat: remove component '{component_name}'",
    )
    catalog.ingest(db, dp, descriptor, commit)
    catalog.record_event(
        db, type_="component.removed", message=f"Removed component '{component_name}'",
        actor=actor, data_product=dp, payload={"component": component_name, "commit": commit},
    )
    run_policies(db, dp, descriptor, trigger="save")
    return descriptor


def add_dependency(db: Session, dp: DataProduct, port_urn: str, actor: User) -> Descriptor:
    """Record that this data product consumes another product's output port."""
    _require_editable(dp)
    descriptor = read_descriptor(dp)
    if port_urn in descriptor.spec.depends_on:
        return descriptor
    if catalog.resolve_output_port(db, port_urn) is None:
        raise LifecycleError(f"'{port_urn}' is not a published output port")
    descriptor.spec.depends_on.append(port_urn)
    commit = repository_service.commit(
        repo_slug(dp),
        {DESCRIPTOR_PATH: serialize(descriptor)},
        author=actor.display_name,
        email=actor.email,
        message=f"feat: consume {port_urn}",
    )
    catalog.ingest(db, dp, descriptor, commit)
    catalog.record_event(
        db, type_="dependency.added", message=f"Now consuming {port_urn}",
        actor=actor, data_product=dp, payload={"urn": port_urn, "commit": commit},
    )
    return descriptor


# --------------------------------------------------------------------------
# lifecycle transitions
# --------------------------------------------------------------------------
def submit_for_review(db: Session, dp: DataProduct, actor: User) -> PolicyReport:
    if dp.lifecycle not in (LifecycleState.DRAFT, LifecycleState.RELEASED, LifecycleState.PUBLISHED):
        raise LifecycleError(f"cannot submit a data product in state '{dp.lifecycle}'")
    report = run_policies(db, dp, trigger="release")
    if not report.passed:
        raise LifecycleError(
            f"{len(report.errors)} governance error(s) must be fixed before review"
        )
    dp.lifecycle = LifecycleState.IN_REVIEW
    catalog.record_event(
        db, type_="lifecycle.submitted", message="Submitted for federated governance review",
        actor=actor, data_product=dp,
    )
    return report


def release(db: Session, dp: DataProduct, *, version: str, notes: str, actor: User) -> DataProductVersion:
    """Cut an immutable version: bump the descriptor, commit, tag, snapshot."""
    if dp.lifecycle not in (LifecycleState.IN_REVIEW, LifecycleState.DRAFT):
        raise LifecycleError(f"cannot release from state '{dp.lifecycle}'")
    if db.execute(
        select(DataProductVersion).where(
            DataProductVersion.data_product_id == dp.id, DataProductVersion.version == version
        )
    ).scalars().first():
        raise LifecycleError(f"version {version} already exists")

    descriptor = read_descriptor(dp)
    descriptor.metadata.version = version
    report = evaluate(PolicyContext(descriptor=descriptor, resolve_dependency=catalog.dependency_resolver(db)))
    if not report.passed:
        raise LifecycleError(f"{len(report.errors)} governance error(s) block the release")

    raw = serialize(descriptor)
    commit = repository_service.commit(
        repo_slug(dp),
        {dp.descriptor_path or DESCRIPTOR_PATH: raw},
        author=actor.display_name,
        email=actor.email,
        message=f"release: {version}",
    )
    repository_service.tag(
        repo_slug(dp), f"v{version}", notes or f"Release {version}",
        author=actor.display_name, email=actor.email,
    )

    snapshot = DataProductVersion(
        data_product_id=dp.id,
        version=version,
        descriptor_yaml=raw,
        commit_sha=commit,
        notes=notes,
        created_by_id=actor.id,
    )
    db.add(snapshot)
    catalog.ingest(db, dp, descriptor, commit)
    dp.lifecycle = LifecycleState.RELEASED
    db.flush()

    catalog.record_event(
        db, type_="lifecycle.released", message=f"Released version {version}",
        actor=actor, data_product=dp, payload={"version": version, "commit": commit},
    )
    return snapshot


def publish(db: Session, dp: DataProduct, actor: User, *, require_deployment: bool = True) -> DataProduct:
    """Make the data product visible and requestable in the marketplace."""
    from app.models import Deployment, DeploymentStatus
    from app.core.config import settings

    if dp.lifecycle not in (LifecycleState.RELEASED, LifecycleState.RETIRED):
        raise LifecycleError("only a released data product can be published to the marketplace")
    if require_deployment:
        gate_env = settings.marketplace_gate_environment
        deployed = db.execute(
            select(Deployment).where(
                Deployment.data_product_id == dp.id,
                Deployment.environment == gate_env,
                Deployment.status == DeploymentStatus.PROVISIONED,
            )
        ).scalars().first()
        if deployed is None:
            raise LifecycleError(
                f"the data product must be provisioned in '{gate_env}' before it can be published"
            )

    dp.lifecycle = LifecycleState.PUBLISHED
    dp.published_at = datetime.now(timezone.utc)
    db.flush()
    catalog.refresh_unresolved_edges(db)
    catalog.record_event(
        db, type_="marketplace.published", message="Published to the marketplace",
        actor=actor, data_product=dp,
    )
    return dp


def retire(db: Session, dp: DataProduct, actor: User, reason: str = "") -> DataProduct:
    dp.lifecycle = LifecycleState.RETIRED
    catalog.record_event(
        db, type_="lifecycle.retired", message=reason or "Retired", actor=actor, data_product=dp,
    )
    return dp


def _require_editable(dp: DataProduct) -> None:
    if dp.lifecycle == LifecycleState.IN_REVIEW:
        raise LifecycleError(
            "the descriptor is frozen while the data product is under governance review"
        )
    if dp.lifecycle == LifecycleState.RETIRED:
        raise LifecycleError("a retired data product cannot be edited")
