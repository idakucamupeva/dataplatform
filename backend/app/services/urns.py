"""URN minting and parsing.

    data product : urn:dmp:<domain>:<name>:<major>
    component    : urn:dmp:<domain>:<name>:<major>:<component>

The *major* version is part of the identity on purpose: a breaking change to a
data product produces a new URN, so consumers bound to `:0` keep resolving to
the contract they signed up for.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class ParsedUrn:
    namespace: str
    domain: str
    name: str
    major: str
    component: str | None = None

    @property
    def data_product_urn(self) -> str:
        return f"urn:{self.namespace}:{self.domain}:{self.name}:{self.major}"

    @property
    def is_component(self) -> bool:
        return self.component is not None


def major_of(version: str) -> str:
    return version.split(".", 1)[0]


def data_product_urn(domain: str, name: str, version: str) -> str:
    return f"urn:{settings.urn_namespace}:{domain}:{name}:{major_of(version)}"


def component_urn(dp_urn: str, component_name: str) -> str:
    return f"{dp_urn}:{component_name}"


def parse_urn(urn: str) -> ParsedUrn | None:
    parts = urn.split(":")
    if len(parts) < 5 or parts[0] != "urn":
        return None
    _, namespace, domain, name, major, *rest = parts
    return ParsedUrn(
        namespace=namespace,
        domain=domain,
        name=name,
        major=major,
        component=rest[0] if rest else None,
    )


def slugify(value: str) -> str:
    out = []
    prev_dash = False
    for ch in value.strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash and out:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-")
