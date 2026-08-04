"""The descriptor is the source of truth — these are its rules."""

from __future__ import annotations

import pytest

from app.services.descriptor_io import DescriptorError, parse_descriptor, serialize

MINIMAL = """
apiVersion: dataproduct.dmp.io/v1
kind: DataProduct
metadata:
  name: customer-360
  domain: sales
  version: 1.2.3
  description: A view of the customer.
  owner: user:alice
  email: sales@acme.io
spec:
  components: []
  dependsOn: []
"""


def test_identifiers_are_derived_not_authored():
    descriptor = parse_descriptor(MINIMAL)
    # the major version is part of the identity, the minor and patch are not
    assert descriptor.metadata.id == "urn:dmp:sales:customer-360:1"
    assert descriptor.metadata.display_name == "Customer 360"


def test_component_urns_are_namespaced_by_the_product():
    raw = MINIMAL.replace(
        "  components: []",
        "  components:\n"
        "    - name: snapshot\n"
        "      kind: outputport\n"
        "      technology: snowflake\n",
    )
    descriptor = parse_descriptor(raw)
    assert descriptor.spec.components[0].id == "urn:dmp:sales:customer-360:1:snapshot"


def test_round_trip_is_stable():
    once = serialize(parse_descriptor(MINIMAL))
    twice = serialize(parse_descriptor(once))
    assert once == twice


def test_empty_optional_fields_are_pruned():
    raw = MINIMAL.replace(
        "  components: []",
        "  components:\n    - name: store\n      kind: storage\n      technology: s3\n",
    )
    out = serialize(parse_descriptor(raw))
    # an output-port-only field must not appear on a storage component
    assert "outputPortType" not in out
    assert "specific" in out or "kind: storage" in out


def test_a_name_that_is_not_a_slug_is_rejected():
    with pytest.raises(DescriptorError) as excinfo:
        parse_descriptor(MINIMAL.replace("customer-360", "Customer 360"))
    assert any("name" in detail["path"] for detail in excinfo.value.details)


def test_a_non_semantic_version_is_rejected():
    with pytest.raises(DescriptorError):
        parse_descriptor(MINIMAL.replace("version: 1.2.3", "version: v1"))


def test_broken_yaml_is_reported_as_such():
    with pytest.raises(DescriptorError) as excinfo:
        parse_descriptor("metadata: name: nope:")
    assert "YAML" in str(excinfo.value)
