"""Enumerations shared by the persistence layer and the API contracts."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Platform-wide role. Ownership of a single data product is modelled
    separately (see :class:`app.models.catalog.DataProduct.owner_id`)."""

    ADMIN = "admin"          # platform team: templates, domains, policies
    GOVERNANCE = "governance"  # federated governance: reviews releases
    USER = "user"            # producer and/or consumer


class LifecycleState(StrEnum):
    """Where a data product sits on its way to the marketplace."""

    DRAFT = "draft"              # scaffolded, freely editable
    IN_REVIEW = "in_review"      # submitted for federated governance review
    RELEASED = "released"        # an immutable version has been cut
    PUBLISHED = "published"      # visible & requestable in the marketplace
    RETIRED = "retired"


class ComponentKind(StrEnum):
    """The Witboost/data-mesh component taxonomy."""

    OUTPUT_PORT = "outputport"
    STORAGE = "storage"
    WORKLOAD = "workload"
    OBSERVABILITY = "observability"


class DeploymentStatus(StrEnum):
    NOT_DEPLOYED = "not_deployed"
    PROVISIONING = "provisioning"
    PROVISIONED = "provisioned"
    FAILED = "failed"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AccessRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"
