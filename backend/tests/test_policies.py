"""Computational governance: what the platform refuses to let through."""

from __future__ import annotations

from app.schemas.descriptor import (
    Component,
    DataContract,
    DataProductMetadata,
    DataProductSpec,
    Descriptor,
    SchemaColumn,
    ServiceLevel,
)
from app.services.descriptor_io import normalise
from app.services.policies import PolicyContext, evaluate


def build(*, components=None, maturity="tactical", depends_on=None, description=None) -> Descriptor:
    return normalise(
        Descriptor(
            metadata=DataProductMetadata(
                name="customer-360",
                domain="sales",
                version="1.0.0",
                description=description if description is not None else
                "A deduplicated view of every customer, refreshed daily for analytics.",
                owner="user:alice",
                email="sales@acme.io",
                maturity=maturity,
                tags=["customer"],
            ),
            spec=DataProductSpec(components=components or [], dependsOn=depends_on or []),
        )
    )


def output_port(**overrides) -> Component:
    contract = DataContract(
        termsAndConditions=overrides.pop("terms", "Internal use only."),
        endpoint="snowflake://ANALYTICS/SALES/CUSTOMER",
        schema=overrides.pop("columns", [SchemaColumn(name="customer_id", description="Key.")]),
        SLA=ServiceLevel(intervalOfChange="1 day", timeliness="2 hours", upTime="99.9%"),
    )
    return Component(
        name=overrides.pop("name", "snapshot"),
        description="The published snapshot.",
        kind="outputport",
        technology="snowflake",
        dataContract=contract,
        **overrides,
    )


def storage() -> Component:
    return Component(name="store", description="Owned storage.", kind="storage", technology="delta-lake")


def observability() -> Component:
    return Component(
        name="quality", description="Quality checks.", kind="observability", technology="great-expectations",
    )


def ids(report) -> set[str]:
    return {finding.policy_id for finding in report.errors}


def test_a_product_without_an_output_port_cannot_be_released():
    report = evaluate(PolicyContext(descriptor=build()))
    assert not report.passed
    assert "interface-exists" in ids(report)


def test_a_complete_product_passes():
    report = evaluate(PolicyContext(descriptor=build(components=[storage(), output_port(), observability()])))
    assert report.passed, [f.message for f in report.errors]


def test_an_output_port_without_a_schema_is_blocked():
    port = output_port(columns=[])
    report = evaluate(PolicyContext(descriptor=build(components=[storage(), observability(), port])))
    assert "contract-complete" in ids(report)


def test_personal_data_must_not_be_classified_as_internal():
    port = output_port(
        columns=[SchemaColumn(name="email", description="Contact.", pii=True, classification="internal")],
    )
    report = evaluate(PolicyContext(descriptor=build(components=[storage(), observability(), port])))
    errors = [f for f in report.errors if f.policy_id == "pii-protected"]
    assert errors and "public/internal" in errors[0].message


def test_personal_data_needs_terms_of_use():
    port = output_port(
        terms="",
        columns=[SchemaColumn(name="email", description="Contact.", pii=True, classification="confidential")],
    )
    report = evaluate(PolicyContext(descriptor=build(components=[storage(), observability(), port])))
    assert any("terms and conditions" in f.message for f in report.errors)


def test_a_strategic_product_must_be_observable():
    report = evaluate(PolicyContext(descriptor=build(components=[storage(), output_port()], maturity="strategic")))
    assert "observable" in ids(report)
    # the same omission is only a warning for a tactical product
    tactical = evaluate(PolicyContext(descriptor=build(components=[storage(), output_port()])))
    assert "observable" not in ids(tactical)
    assert any(f.policy_id == "observable" for f in tactical.warnings)


def test_duplicate_component_names_are_rejected():
    report = evaluate(
        PolicyContext(descriptor=build(components=[output_port(), output_port(), storage(), observability()]))
    )
    assert "topology-sound" in ids(report)


def test_a_dependency_that_resolves_to_nothing_is_blocked():
    descriptor = build(
        components=[storage(), output_port(), observability()],
        depends_on=["urn:dmp:crm:orders:0:events"],
    )
    report = evaluate(PolicyContext(descriptor=descriptor, resolve_dependency=lambda _urn: None))
    assert "dependencies-resolvable" in ids(report)

    resolved = evaluate(PolicyContext(descriptor=descriptor, resolve_dependency=lambda _urn: "Order Events"))
    assert resolved.passed


def test_a_thin_description_is_a_warning_not_a_blocker():
    report = evaluate(
        PolicyContext(descriptor=build(components=[storage(), output_port(), observability()], description="Data."))
    )
    assert report.passed
    assert any(f.policy_id == "documented" for f in report.warnings)
