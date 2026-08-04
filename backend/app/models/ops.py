"""Operational tables: deployments, policy evaluations, access, audit."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.catalog import Component, DataProduct, DataProductVersion
from app.models.enums import AccessRequestStatus, DeploymentStatus
from app.models.user import User, utcnow


class Deployment(Base):
    """One provisioning run of one data product version into one environment."""

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_product_id: Mapped[int] = mapped_column(ForeignKey("data_products.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_product_versions.id", ondelete="SET NULL"), nullable=True
    )
    version_label: Mapped[str] = mapped_column(String(32), default="")
    environment: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[DeploymentStatus] = mapped_column(String(32), default=DeploymentStatus.PROVISIONING)
    operation: Mapped[str] = mapped_column(String(16), default="provision")  # provision | destroy
    logs: Mapped[list] = mapped_column(JSON, default=list)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    data_product: Mapped[DataProduct] = relationship()
    version: Mapped[DataProductVersion | None] = relationship()
    requested_by: Mapped[User | None] = relationship(lazy="joined")


class PolicyEvaluation(Base):
    """Result of running the computational-governance policy set."""

    __tablename__ = "policy_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_product_id: Mapped[int] = mapped_column(ForeignKey("data_products.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")  # manual | save | release | deploy
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    error_count: Mapped[int] = mapped_column(default=0)
    warning_count: Mapped[int] = mapped_column(default=0)
    results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    data_product: Mapped[DataProduct] = relationship()


class AccessRequest(Base):
    """A consumer asking the owning domain for access to an output port."""

    __tablename__ = "access_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_product_id: Mapped[int] = mapped_column(ForeignKey("data_products.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id", ondelete="SET NULL"), nullable=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    consumer_dp_urn: Mapped[str] = mapped_column(String(255), default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[AccessRequestStatus] = mapped_column(String(32), default=AccessRequestStatus.PENDING)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    data_product: Mapped[DataProduct] = relationship(lazy="joined")
    component: Mapped[Component | None] = relationship(lazy="joined")
    requester: Mapped[User] = relationship(foreign_keys=[requester_id], lazy="joined")
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id], lazy="joined")


class Event(Base):
    """Append-only activity feed / audit trail."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    data_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_products.id", ondelete="CASCADE"), nullable=True, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    actor: Mapped[User | None] = relationship(lazy="joined")
    data_product: Mapped[DataProduct | None] = relationship(lazy="joined")
