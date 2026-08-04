"""The scaffolder: declarative templates for data products and components.

A template is a YAML file in ``app/scaffolder_templates``.  It declares

* the *form* the UI must render (``parameters`` -> sections -> fields), and
* the *output*: for a data product template a full descriptor plus the initial
  repository files, for a component template a component block that gets
  merged into an existing descriptor plus any extra repository files.

Rendering rules
---------------
Structured blocks (``descriptor``, ``component``) are authored as real YAML and
rendered node-by-node, so template authors never fight with indentation:

* a string containing ``{{ ... }}`` is rendered with Jinja and stays a string;
* a string that is *exactly* ``${name}`` is replaced by the raw parameter value
  (list, bool, number, mapping — whatever the form produced);
* a mapping key or list item whose value renders to ``None`` is dropped.

File bodies are plain Jinja templates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, TemplateError

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "scaffolder_templates"
RAW_REF_RE = re.compile(r"^\$\{([a-zA-Z0-9_.]+)\}$")

_env = Environment(undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)  # noqa: S701
_env.filters["yaml"] = lambda v: yaml.safe_dump(v, default_flow_style=False).rstrip()


class TemplateError_(Exception):
    pass


@dataclass(frozen=True)
class TemplateFile:
    path: str
    content: str


@dataclass
class Template:
    id: str
    name: str
    type: str  # "dataproduct" | "component"
    description: str = ""
    kind: str = ""  # component kind, for type == component
    technology: str = ""
    platform: str = ""
    provisioner: str = ""
    icon: str = "box"
    tags: list[str] = field(default_factory=list)
    parameters: list[dict] = field(default_factory=list)
    descriptor: dict | None = None
    component: dict | None = None
    files: list[TemplateFile] = field(default_factory=list)

    def default_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for section in self.parameters:
            for fld in section.get("fields", []):
                if "default" in fld:
                    values[fld["name"]] = fld["default"]
        return values

    def field_specs(self) -> list[dict]:
        return [fld for section in self.parameters for fld in section.get("fields", [])]

    def as_summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "kind": self.kind,
            "description": self.description,
            "technology": self.technology,
            "platform": self.platform,
            "provisioner": self.provisioner,
            "icon": self.icon,
            "tags": self.tags,
        }

    def as_detail(self) -> dict:
        return {**self.as_summary(), "parameters": self.parameters}


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def _lookup(ctx: dict[str, Any], dotted: str) -> Any:
    node: Any = ctx
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise TemplateError_(f"unknown template parameter '{dotted}'")
    return node


def render_node(node: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(node, str):
        raw_ref = RAW_REF_RE.match(node.strip())
        if raw_ref:
            return _lookup(ctx, raw_ref.group(1))
        if "{{" in node or "{%" in node:
            try:
                return _env.from_string(node).render(**ctx)
            except TemplateError as exc:
                raise TemplateError_(f"failed to render '{node[:60]}': {exc}") from exc
        return node
    if isinstance(node, list):
        rendered = [render_node(item, ctx) for item in node]
        return [item for item in rendered if item is not None]
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            rendered = render_node(value, ctx)
            if rendered is None or rendered == "":
                continue
            out[key] = rendered
        return out
    return node


_ALLOWED_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}


def _normalise_schema(value: Any, title: str, errors: list[str]) -> list[dict]:
    """Coerce the rows of a `schema` field into data-contract columns."""
    if not isinstance(value, list):
        errors.append(f"'{title}' must be a list of columns")
        return []
    columns: list[dict] = []
    seen: set[str] = set()
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict) or not str(row.get("name", "")).strip():
            errors.append(f"'{title}' row {index} needs a column name")
            continue
        name = str(row["name"]).strip()
        if name in seen:
            errors.append(f"'{title}' declares column '{name}' twice")
            continue
        seen.add(name)
        classification = str(row.get("classification") or "internal")
        if classification not in _ALLOWED_CLASSIFICATIONS:
            classification = "internal"
        columns.append(
            {
                "name": name,
                "dataType": str(row.get("dataType") or "string"),
                "description": str(row.get("description") or ""),
                "nullable": bool(row.get("nullable", True)),
                "pii": bool(row.get("pii", False)),
                "classification": classification,
            }
        )
    return columns


def render_text(body: str, ctx: dict[str, Any]) -> str:
    try:
        return _env.from_string(body).render(**ctx)
    except TemplateError as exc:
        raise TemplateError_(f"failed to render file body: {exc}") from exc


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
class TemplateRegistry:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or TEMPLATES_DIR
        self._templates: dict[str, Template] = {}
        self.reload()

    def reload(self) -> None:
        self._templates = {}
        for path in sorted(self.directory.glob("*.y*ml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            template = Template(
                id=data["id"],
                name=data.get("name", data["id"]),
                type=data.get("type", "component"),
                description=data.get("description", ""),
                kind=data.get("kind", ""),
                technology=data.get("technology", ""),
                platform=data.get("platform", ""),
                provisioner=data.get("provisioner", ""),
                icon=data.get("icon", "box"),
                tags=data.get("tags", []) or [],
                parameters=data.get("parameters", []) or [],
                descriptor=data.get("descriptor"),
                component=data.get("component"),
                files=[TemplateFile(path=f["path"], content=f.get("content", "")) for f in data.get("files", []) or []],
            )
            self._templates[template.id] = template

    def all(self, type_: str | None = None, kind: str | None = None) -> list[Template]:
        items = list(self._templates.values())
        if type_:
            items = [t for t in items if t.type == type_]
        if kind:
            items = [t for t in items if t.kind == kind]
        return sorted(items, key=lambda t: (t.type, t.kind, t.name))

    def get(self, template_id: str) -> Template:
        try:
            return self._templates[template_id]
        except KeyError:
            raise TemplateError_(f"unknown template '{template_id}'") from None

    # -- validation --------------------------------------------------------
    def validate_values(self, template: Template, values: dict[str, Any]) -> dict[str, Any]:
        """Coerce + check submitted form values against the template's fields."""
        resolved: dict[str, Any] = {}
        errors: list[str] = []
        for spec in template.field_specs():
            name = spec["name"]
            value = values.get(name, spec.get("default"))
            ftype = spec.get("type", "string")
            required = spec.get("required", False)

            if value in (None, "", []) and required:
                errors.append(f"'{spec.get('title', name)}' is required")
                resolved[name] = value
                continue
            if value in (None, ""):
                value = {"boolean": False, "tags": [], "multiselect": [], "list": [], "schema": []}.get(ftype, "")

            if ftype == "schema":
                value = _normalise_schema(value, spec.get("title", name), errors)
            elif ftype == "boolean":
                value = bool(value)
            elif ftype == "number":
                try:
                    value = float(value) if isinstance(value, str) and "." in value else int(value)
                except (TypeError, ValueError):
                    errors.append(f"'{spec.get('title', name)}' must be a number")
            elif ftype in ("tags", "multiselect", "list"):
                if isinstance(value, str):
                    value = [v.strip() for v in value.split(",") if v.strip()]
                value = list(value or [])
            elif ftype == "select":
                options = [o["value"] if isinstance(o, dict) else o for o in spec.get("options", [])]
                if options and value not in options and not spec.get("optionsFrom"):
                    errors.append(f"'{spec.get('title', name)}' must be one of {', '.join(map(str, options))}")
            else:
                value = str(value)
                pattern = spec.get("pattern")
                if pattern and value and not re.match(pattern, value):
                    errors.append(spec.get("patternMessage") or f"'{spec.get('title', name)}' has an invalid format")

            resolved[name] = value

        if errors:
            raise TemplateError_("; ".join(errors))
        return resolved

    # -- rendering ---------------------------------------------------------
    def render_files(self, template: Template, ctx: dict[str, Any]) -> dict[str, str]:
        out: dict[str, str] = {}
        for tf in template.files:
            path = render_text(tf.path, ctx)
            out[path] = render_text(tf.content, ctx)
        return out


template_registry = TemplateRegistry()
