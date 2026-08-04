"""Provisioner interface.

A provisioner turns one component of a descriptor into real infrastructure.
In a production deployment each of these would call Terraform, the Snowflake
API, the Kafka admin API and so on; here they are deterministic simulators
that validate the component's `specific` block and emit the resource
identifiers a real adapter would return.  The interface is the point: the
coordinator knows nothing about any particular technology.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.descriptor import Component, Descriptor


@dataclass
class ProvisionResult:
    ok: bool
    logs: list[str] = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    error: str = ""


class Provisioner:
    """Base class for technology adapters."""

    #: value matched against `component.technology`
    technology: str = ""
    #: human readable target system
    platform: str = ""
    #: keys required inside `component.specific`
    required_keys: tuple[str, ...] = ()

    def validate(self, component: Component, descriptor: Descriptor, environment: str) -> list[str]:
        missing = [key for key in self.required_keys if not component.specific.get(key)]
        return [f"`specific.{key}` is required by the {self.technology} provisioner" for key in missing]

    def provision(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        raise NotImplementedError

    def destroy(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        return ProvisionResult(
            ok=True,
            logs=[f"[{self.technology}] removed resources for '{component.name}' from {environment}"],
        )

    # -- helpers -----------------------------------------------------------
    def env_prefix(self, environment: str) -> str:
        return {"development": "dev", "qa": "qa", "production": "prd"}.get(environment, environment[:3])

    def qualify(self, environment: str, value: str) -> str:
        return f"{self.env_prefix(environment)}_{value}"


class ProvisionerRegistry:
    def __init__(self) -> None:
        self._by_technology: dict[str, Provisioner] = {}

    def register(self, provisioner: Provisioner) -> None:
        self._by_technology[provisioner.technology] = provisioner

    def for_component(self, component: Component) -> Provisioner | None:
        return self._by_technology.get(component.technology)

    def all(self) -> list[Provisioner]:
        return sorted(self._by_technology.values(), key=lambda p: p.technology)


registry = ProvisionerRegistry()
