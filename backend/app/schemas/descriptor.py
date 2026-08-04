"""The Data Product Descriptor.

This module defines the *contract* of the file that lives in every data product
repository (`data-product-descriptor.yaml`).  That file — not the database — is
the source of truth for a data product's metadata; the platform parses it,
validates it, projects it into the catalog and hands it to provisioners.

The shape follows the data mesh descriptor conventions popularised by Witboost
and the Open Data Mesh specification: a Kubernetes-style envelope
(`apiVersion` / `kind` / `metadata` / `spec`) wrapping a list of components,
each of which is an output port, a storage area, a workload or an
observability component.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ComponentKind

API_VERSION = "dataproduct.dmp.io/v1"
NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{1,62}[a-z0-9])$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class DescriptorModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")


# --------------------------------------------------------------------------
# Data contract
# --------------------------------------------------------------------------
class SchemaColumn(DescriptorModel):
    name: str
    data_type: str = Field(default="string", alias="dataType")
    description: str = ""
    nullable: bool = True
    pii: bool = False
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    tags: list[str] = Field(default_factory=list)


class ServiceLevel(DescriptorModel):
    """Service levels a consumer can rely on."""

    interval_of_change: str = Field(default="", alias="intervalOfChange")
    timeliness: str = ""
    upTime: str = ""
    freshness: str = ""


class DataContract(DescriptorModel):
    """What the producing domain promises to a consumer of an output port."""

    terms_and_conditions: str = Field(default="", alias="termsAndConditions")
    endpoint: str = ""
    schema_: list[SchemaColumn] = Field(default_factory=list, alias="schema")
    sla: ServiceLevel = Field(default_factory=ServiceLevel, alias="SLA")
    billing_policy: str = Field(default="", alias="billingPolicy")


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------
class Component(DescriptorModel):
    id: str = ""
    name: str
    display_name: str = Field(default="", alias="displayName")
    description: str = ""
    kind: ComponentKind
    version: str = "0.1.0"
    technology: str = ""
    platform: str = ""
    # Which scaffolder template produced this component; provisioning uses it
    # to pick the right provisioner adapter.
    use_case_template_id: str = Field(default="", alias="useCaseTemplateId")
    infrastructure_template_id: str = Field(default="", alias="infrastructureTemplateId")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    tags: list[str] = Field(default_factory=list)
    # Output-port only
    output_port_type: str = Field(default="", alias="outputPortType")
    data_contract: DataContract | None = Field(default=None, alias="dataContract")
    # Free-form, technology specific block consumed by the provisioner
    specific: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError(
                f"component name '{v}' must be lowercase alphanumeric with dashes (3-64 chars)"
            )
        return v


class DataProductMetadata(DescriptorModel):
    id: str = ""
    name: str
    display_name: str = Field(default="", alias="displayName")
    domain: str
    version: str = "0.1.0"
    description: str = ""
    # `user:alice` / `group:sales-data-team`
    owner: str = ""
    email: str = ""
    maturity: Literal["tactical", "strategic"] = "tactical"
    tags: list[str] = Field(default_factory=list)
    information_sla: str = Field(default="", alias="informationSLA")

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError(
                f"data product name '{v}' must be lowercase alphanumeric with dashes (3-64 chars)"
            )
        return v

    @field_validator("version")
    @classmethod
    def _valid_version(cls, v: str) -> str:
        if not SEMVER_RE.match(v):
            raise ValueError(f"version '{v}' must be semantic (MAJOR.MINOR.PATCH)")
        return v


class DataProductSpec(DescriptorModel):
    components: list[Component] = Field(default_factory=list)
    # URNs of output ports of *other* data products this one consumes.
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")


class Descriptor(DescriptorModel):
    api_version: str = Field(default=API_VERSION, alias="apiVersion")
    kind: Literal["DataProduct"] = "DataProduct"
    metadata: DataProductMetadata
    spec: DataProductSpec = Field(default_factory=DataProductSpec)

    # -- convenience ------------------------------------------------------
    def components_of(self, kind: ComponentKind) -> list[Component]:
        return [c for c in self.spec.components if c.kind == kind]

    @property
    def output_ports(self) -> list[Component]:
        return self.components_of(ComponentKind.OUTPUT_PORT)

    def component(self, name: str) -> Component | None:
        return next((c for c in self.spec.components if c.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        """Alias-keyed, None-stripped dict ready to be dumped as YAML."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")
