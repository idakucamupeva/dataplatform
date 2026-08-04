"""Computational governance.

In a data mesh, governance is *federated*: the platform team encodes the global
rules once and every domain gets them applied automatically, instead of a
central board reviewing spreadsheets.  This module is that encoding.

Each policy is a small pure function over a :class:`PolicyContext`.  Policies
run on every descriptor save (advisory) and again as a hard gate before a
release or a production deployment: a descriptor with `error` findings cannot
be released, and a data product that has never passed cannot reach the
marketplace.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

from app.models.enums import ComponentKind, Severity
from app.schemas.descriptor import Component, Descriptor

MIN_DESCRIPTION_LENGTH = 40


class DependencyResolver(Protocol):
    """Resolves an output-port URN to a human label, or ``None`` if unknown."""

    def __call__(self, urn: str) -> str | None: ...


@dataclass
class PolicyContext:
    descriptor: Descriptor
    resolve_dependency: DependencyResolver | None = None
    environment: str | None = None


@dataclass
class Finding:
    policy_id: str
    policy_name: str
    severity: Severity
    message: str
    target: str = ""
    remediation: str = ""
    category: str = "general"

    def as_dict(self) -> dict:
        return {
            "policyId": self.policy_id,
            "policyName": self.policy_name,
            "severity": str(self.severity),
            "message": self.message,
            "target": self.target,
            "remediation": self.remediation,
            "category": self.category,
        }


@dataclass
class PolicyReport:
    findings: list[Finding] = field(default_factory=list)
    evaluated: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.WARNING]

    @property
    def passed(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "errorCount": len(self.errors),
            "warningCount": len(self.warnings),
            "evaluatedPolicies": self.evaluated,
            "findings": [f.as_dict() for f in self.findings],
        }


@dataclass
class Policy:
    id: str
    name: str
    description: str
    category: str
    check: Callable[[PolicyContext], Iterable[Finding]]

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
        }


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _finding(policy: str, name: str, severity: Severity, message: str, **kw) -> Finding:
    return Finding(policy_id=policy, policy_name=name, severity=severity, message=message, **kw)


def _ports(ctx: PolicyContext) -> list[Component]:
    return ctx.descriptor.output_ports


# --------------------------------------------------------------------------
# policies
# --------------------------------------------------------------------------
def _check_ownership(ctx: PolicyContext):
    meta = ctx.descriptor.metadata
    if not meta.owner:
        yield _finding(
            "ownership-declared", "Ownership is declared", Severity.ERROR,
            "The data product has no owner.",
            target=meta.id, category="ownership",
            remediation="Set `metadata.owner` to a user or group, e.g. `group:sales-data-team`.",
        )
    if not meta.email:
        yield _finding(
            "ownership-declared", "Ownership is declared", Severity.ERROR,
            "No contact address: consumers would have nobody to ask.",
            target=meta.id, category="ownership",
            remediation="Set `metadata.email` to a monitored mailbox.",
        )


def _check_documentation(ctx: PolicyContext):
    meta = ctx.descriptor.metadata
    if len(meta.description.strip()) < MIN_DESCRIPTION_LENGTH:
        yield _finding(
            "documented", "Product is documented", Severity.WARNING,
            f"The description is shorter than {MIN_DESCRIPTION_LENGTH} characters.",
            target=meta.id, category="documentation",
            remediation="Explain what question this data product answers and for whom.",
        )
    if not meta.tags:
        yield _finding(
            "documented", "Product is documented", Severity.INFO,
            "No tags: the product will be hard to find in the marketplace.",
            target=meta.id, category="documentation",
            remediation="Add a few discovery tags such as the subject area or refresh cadence.",
        )
    for component in ctx.descriptor.spec.components:
        if not component.description.strip():
            yield _finding(
                "documented", "Product is documented", Severity.WARNING,
                f"Component '{component.name}' has no description.",
                target=component.id, category="documentation",
            )


def _check_has_output_port(ctx: PolicyContext):
    if not _ports(ctx):
        yield _finding(
            "interface-exists", "The product exposes an interface", Severity.ERROR,
            "A data product with no output port cannot be consumed by anyone.",
            target=ctx.descriptor.metadata.id, category="interface",
            remediation="Add at least one output port component before releasing.",
        )


def _check_data_contracts(ctx: PolicyContext):
    for port in _ports(ctx):
        contract = port.data_contract
        if contract is None or not contract.schema_:
            yield _finding(
                "contract-complete", "Output ports publish a data contract", Severity.ERROR,
                f"Output port '{port.name}' publishes no schema.",
                target=port.id, category="contract",
                remediation="Declare the columns consumers may rely on in `dataContract.schema`.",
            )
            continue
        if not contract.terms_and_conditions.strip():
            yield _finding(
                "contract-complete", "Output ports publish a data contract", Severity.WARNING,
                f"Output port '{port.name}' has no terms and conditions.",
                target=port.id, category="contract",
            )
        if not contract.endpoint.strip():
            yield _finding(
                "contract-complete", "Output ports publish a data contract", Severity.ERROR,
                f"Output port '{port.name}' declares no endpoint, so consumers cannot reach it.",
                target=port.id, category="contract",
            )
        undocumented = [c.name for c in contract.schema_ if not c.description.strip()]
        if undocumented:
            preview = ", ".join(undocumented[:5]) + ("…" if len(undocumented) > 5 else "")
            yield _finding(
                "contract-complete", "Output ports publish a data contract", Severity.INFO,
                f"Undocumented columns on '{port.name}': {preview}.",
                target=port.id, category="contract",
            )


def _check_service_levels(ctx: PolicyContext):
    for port in _ports(ctx):
        sla = port.data_contract.sla if port.data_contract else None
        if sla is None or not (sla.timeliness or sla.interval_of_change or sla.upTime):
            yield _finding(
                "sla-declared", "Service levels are declared", Severity.WARNING,
                f"Output port '{port.name}' promises no service level.",
                target=port.id, category="contract",
                remediation="Fill in `dataContract.SLA` — at minimum timeliness and availability.",
            )


def _check_personal_data(ctx: PolicyContext):
    """The one rule that is genuinely non-negotiable in most organisations."""
    for port in _ports(ctx):
        if not port.data_contract:
            continue
        pii_columns = [c for c in port.data_contract.schema_ if c.pii]
        if not pii_columns:
            continue
        under_classified = [c.name for c in pii_columns if c.classification in ("public", "internal")]
        if under_classified:
            yield _finding(
                "pii-protected", "Personal data is classified and governed", Severity.ERROR,
                f"Personal data on '{port.name}' is classified as public/internal: "
                f"{', '.join(under_classified)}.",
                target=port.id, category="privacy",
                remediation="Classify personal columns as `confidential` or `restricted`.",
            )
        if not port.data_contract.terms_and_conditions.strip():
            yield _finding(
                "pii-protected", "Personal data is classified and governed", Severity.ERROR,
                f"Output port '{port.name}' exposes personal data without terms and conditions.",
                target=port.id, category="privacy",
                remediation="State the lawful basis and the permitted use of the personal data.",
            )
        if "pii" not in [t.lower() for t in port.tags]:
            yield _finding(
                "pii-protected", "Personal data is classified and governed", Severity.WARNING,
                f"Output port '{port.name}' exposes personal data but is not tagged `pii`.",
                target=port.id, category="privacy",
            )


def _check_component_topology(ctx: PolicyContext):
    descriptor = ctx.descriptor
    names = [c.name for c in descriptor.spec.components]
    duplicates = {n for n in names if names.count(n) > 1}
    for name in sorted(duplicates):
        yield _finding(
            "topology-sound", "The component topology is sound", Severity.ERROR,
            f"Component name '{name}' is used more than once.",
            target=descriptor.metadata.id, category="structure",
        )
    if _ports(ctx) and not descriptor.components_of(ComponentKind.STORAGE):
        yield _finding(
            "topology-sound", "The component topology is sound", Severity.WARNING,
            "Output ports are published but the product owns no storage area.",
            target=descriptor.metadata.id, category="structure",
            remediation="Data products should own the data they serve rather than read through "
                        "to somebody else's system.",
        )
    if descriptor.components_of(ComponentKind.STORAGE) and not descriptor.components_of(ComponentKind.WORKLOAD):
        yield _finding(
            "topology-sound", "The component topology is sound", Severity.INFO,
            "Storage is declared but no workload populates it.",
            target=descriptor.metadata.id, category="structure",
        )


def _check_observability(ctx: PolicyContext):
    descriptor = ctx.descriptor
    if descriptor.components_of(ComponentKind.OBSERVABILITY):
        return
    strategic = descriptor.metadata.maturity == "strategic"
    yield _finding(
        "observable", "The product is observable", Severity.ERROR if strategic else Severity.WARNING,
        "No observability component: nothing verifies the promises made to consumers."
        + (" Strategic data products must be monitored." if strategic else ""),
        target=descriptor.metadata.id, category="observability",
        remediation="Add a data quality monitor for each output port.",
    )


def _check_dependencies(ctx: PolicyContext):
    descriptor = ctx.descriptor
    declared = list(descriptor.spec.depends_on)
    for component in descriptor.spec.components:
        declared.extend(component.depends_on)

    own_prefix = descriptor.metadata.id + ":"
    for urn in dict.fromkeys(declared):
        if urn.startswith(own_prefix):
            continue
        if not urn.startswith("urn:"):
            yield _finding(
                "dependencies-resolvable", "Dependencies resolve to real output ports", Severity.ERROR,
                f"Dependency '{urn}' is not a URN.",
                target=descriptor.metadata.id, category="lineage",
                remediation="Reference upstream data through the URN of its output port.",
            )
            continue
        if ctx.resolve_dependency is None:
            continue
        if ctx.resolve_dependency(urn) is None:
            yield _finding(
                "dependencies-resolvable", "Dependencies resolve to real output ports", Severity.ERROR,
                f"Dependency '{urn}' does not match any output port published in the mesh.",
                target=descriptor.metadata.id, category="lineage",
                remediation="Consume a published output port, or ask that domain to publish one.",
            )


def _check_versioning(ctx: PolicyContext):
    meta = ctx.descriptor.metadata
    if meta.maturity == "strategic" and meta.version.startswith("0."):
        yield _finding(
            "versioning-honest", "Versioning reflects maturity", Severity.WARNING,
            "A strategic data product still carries a 0.x version.",
            target=meta.id, category="lifecycle",
            remediation="Cut a 1.0.0 release once the interface is stable.",
        )
    for component in ctx.descriptor.spec.components:
        if not component.technology:
            yield _finding(
                "versioning-honest", "Versioning reflects maturity", Severity.WARNING,
                f"Component '{component.name}' declares no technology, so no provisioner can claim it.",
                target=component.id, category="lifecycle",
            )


POLICIES: list[Policy] = [
    Policy("ownership-declared", "Ownership is declared",
           "Every data product names an accountable owner and a contact address.",
           "ownership", _check_ownership),
    Policy("documented", "Product is documented",
           "Descriptions and tags exist so the product can be understood and found.",
           "documentation", _check_documentation),
    Policy("interface-exists", "The product exposes an interface",
           "A data product must publish at least one output port.",
           "interface", _check_has_output_port),
    Policy("contract-complete", "Output ports publish a data contract",
           "Each output port declares schema, endpoint and terms of use.",
           "contract", _check_data_contracts),
    Policy("sla-declared", "Service levels are declared",
           "Consumers are told how fresh and how available the data is.",
           "contract", _check_service_levels),
    Policy("pii-protected", "Personal data is classified and governed",
           "Columns carrying personal data are classified and their use is constrained.",
           "privacy", _check_personal_data),
    Policy("topology-sound", "The component topology is sound",
           "Components are uniquely named and the product owns the data it serves.",
           "structure", _check_component_topology),
    Policy("observable", "The product is observable",
           "Quality and freshness of the published data are monitored.",
           "observability", _check_observability),
    Policy("dependencies-resolvable", "Dependencies resolve to real output ports",
           "Upstream data is consumed through published output ports, never through back doors.",
           "lineage", _check_dependencies),
    Policy("versioning-honest", "Versioning reflects maturity",
           "Version numbers and declared technologies match the stated maturity.",
           "lifecycle", _check_versioning),
]


def evaluate(ctx: PolicyContext, policies: Iterable[Policy] | None = None) -> PolicyReport:
    report = PolicyReport()
    for policy in policies or POLICIES:
        report.evaluated.append(policy.id)
        report.findings.extend(policy.check(ctx))
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    report.findings.sort(key=lambda f: (order[f.severity], f.policy_id, f.target))
    return report
