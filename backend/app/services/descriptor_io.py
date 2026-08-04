"""Reading, writing and normalising the descriptor document."""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import ValidationError

from app.schemas.descriptor import Component, Descriptor
from app.services.urns import component_urn, data_product_urn


class DescriptorError(Exception):
    """Raised when a descriptor cannot be parsed or fails schema validation."""

    def __init__(self, message: str, details: list[dict] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class _BlockDumper(yaml.SafeDumper):
    """Keeps the YAML readable: block style, indented sequences."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):  # noqa: FBT001,FBT002
        return super().increase_indent(flow, False)


def _str_presenter(dumper: yaml.Dumper, data: str):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_BlockDumper.add_representer(str, _str_presenter)


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.dump(data, Dumper=_BlockDumper, sort_keys=False, allow_unicode=True, width=100)


def load_yaml(raw: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise DescriptorError(f"descriptor is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise DescriptorError("descriptor must be a YAML mapping")
    return data


def parse_descriptor(raw: str) -> Descriptor:
    """Parse + schema-validate, then stamp derived identifiers."""
    data = load_yaml(raw)
    try:
        descriptor = Descriptor.model_validate(data)
    except ValidationError as exc:
        details = [
            {"path": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in exc.errors()
        ]
        raise DescriptorError("descriptor does not match the Data Product schema", details) from exc
    return normalise(descriptor)


def normalise(descriptor: Descriptor) -> Descriptor:
    """Recompute the identifiers that are derived from other fields.

    URNs are never authored by hand — they are a pure function of
    (domain, name, major version, component name), which keeps them consistent
    no matter how the descriptor was edited.
    """
    meta = descriptor.metadata
    meta.id = data_product_urn(meta.domain, meta.name, meta.version)
    if not meta.display_name:
        meta.display_name = meta.name.replace("-", " ").title()
    for component in descriptor.spec.components:
        component.id = component_urn(meta.id, component.name)
        if not component.display_name:
            component.display_name = component.name.replace("-", " ").title()
    return descriptor


# Keys that stay in the document even when empty, because their absence would
# be meaningful rather than merely tidy.
_ALWAYS_KEEP = {"components", "dependsOn", "specific", "schema"}


def _prune(node: Any, *, keep_all: bool = False) -> Any:
    """Drop keys that carry no information, so the file stays readable."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            cleaned = _prune(value, keep_all=keep_all or key == "specific")
            if keep_all or key in _ALWAYS_KEEP or cleaned not in ("", [], {}, None):
                out[key] = cleaned
        return out
    if isinstance(node, list):
        return [_prune(item, keep_all=keep_all) for item in node]
    return node


def serialize(descriptor: Descriptor) -> str:
    doc = normalise(descriptor).to_dict()
    metadata = _prune(doc.get("metadata", {}))
    metadata.setdefault("tags", doc.get("metadata", {}).get("tags", []))
    spec = doc.get("spec", {})
    components = [_prune(component) for component in spec.get("components", [])]
    # An empty `tags`/`dependsOn` on a component is noise; on the product it is not.
    for component in components:
        for key in ("tags", "dependsOn"):
            if component.get(key) == []:
                component.pop(key)
    return dump_yaml(
        {
            "apiVersion": doc.get("apiVersion", ""),
            "kind": doc.get("kind", "DataProduct"),
            "metadata": metadata,
            "spec": {"components": components, "dependsOn": spec.get("dependsOn", [])},
        }
    )


def component_from_dict(payload: dict[str, Any]) -> Component:
    try:
        return Component.model_validate(payload)
    except ValidationError as exc:
        details = [
            {"path": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in exc.errors()
        ]
        raise DescriptorError("component definition is invalid", details) from exc
