"""Catalog tables.

These tables are a *projection*: the authoritative metadata of a data product
is the descriptor YAML stored in its git repository.  Every time the descriptor
changes it is re-ingested and the rows below are rebuilt from it
(see :mod:`app.services.catalog`).  Keeping the read model in SQL is what makes
search, lineage and marketplace queries cheap.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import ComponentKind, LifecycleState
from app.models.user import User, utcnow


class Domain(Base):
    """A data mesh domain (e.g. `sales`, `marketing`)."""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User | None] = relationship("User", lazy="joined")
    data_products: Mapped[list["DataProduct"]] = relationship(back_populates="domain")


class DataProduct(Base):
    __tablename__ = "data_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    urn: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")

    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    lifecycle: Mapped[LifecycleState] = mapped_column(String(32), default=LifecycleState.DRAFT)
    version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    maturity: Mapped[str] = mapped_column(String(32), default="tactical")
    tags: Mapped[list] = mapped_column(JSON, default=list)

    # git-backed source of truth
    repo_path: Mapped[str] = mapped_column(String(512), default="")
    descriptor_path: Mapped[str] = mapped_column(String(255), default="data-product-descriptor.yaml")
    head_commit: Mapped[str] = mapped_column(String(64), default="")

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    domain: Mapped[Domain] = relationship(back_populates="data_products", lazy="joined")
    owner: Mapped[User] = relationship(lazy="joined")
    components: Mapped[list["Component"]] = relationship(
        back_populates="data_product", cascade="all, delete-orphan", order_by="Component.id"
    )
    versions: Mapped[list["DataProductVersion"]] = relationship(
        back_populates="data_product", cascade="all, delete-orphan", order_by="DataProductVersion.id.desc()"
    )

    @property
    def is_public(self) -> bool:
        return self.lifecycle == LifecycleState.PUBLISHED


class Component(Base):
    """An output port, storage area, workload or observability component."""

    __tablename__ = "components"
    __table_args__ = (UniqueConstraint("data_product_id", "name", name="uq_component_name_per_dp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    data_product_id: Mapped[int] = mapped_column(ForeignKey("data_products.id", ondelete="CASCADE"))
    urn: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(255), default="")
    kind: Mapped[ComponentKind] = mapped_column(String(32), index=True)
    technology: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    use_case_template_id: Mapped[str] = mapped_column(String(128), default="")
    spec: Mapped[dict] = mapped_column(JSON, default=dict)

    data_product: Mapped[DataProduct] = relationship(back_populates="components")


class DataProductVersion(Base):
    """Immutable snapshot of the descriptor, produced on release."""

    __tablename__ = "data_product_versions"
    __table_args__ = (UniqueConstraint("data_product_id", "version", name="uq_version_per_dp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    data_product_id: Mapped[int] = mapped_column(ForeignKey("data_products.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(String(32))
    descriptor_yaml: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    data_product: Mapped[DataProduct] = relationship(back_populates="versions")
    created_by: Mapped[User | None] = relationship(lazy="joined")


class LineageEdge(Base):
    """`source` consumes the output port `target_port_urn` of `target`.

    Rebuilt from the `dependsOn` blocks of every descriptor on ingestion.
    """

    __tablename__ = "lineage_edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_dp_id: Mapped[int] = mapped_column(ForeignKey("data_products.id", ondelete="CASCADE"), index=True)
    target_port_urn: Mapped[str] = mapped_column(String(320), index=True)
    target_dp_urn: Mapped[str] = mapped_column(String(255), index=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    hops: Mapped[int] = mapped_column(Integer, default=1)
