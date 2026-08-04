"""Domain objects -> JSON shapes consumed by the React client."""

from __future__ import annotations

from typing import Any

from app.models import (
    AccessRequest,
    Component,
    ComponentKind,
    DataProduct,
    DataProductVersion,
    Deployment,
    Domain,
    Event,
    PolicyEvaluation,
    User,
)
from app.services.repository import CommitInfo


def user_out(user: User | None) -> dict | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "email": user.email,
        "role": str(user.role),
    }


def domain_out(domain: Domain) -> dict:
    return {
        "id": domain.id,
        "name": domain.name,
        "title": domain.title or domain.name,
        "description": domain.description,
        "owner": user_out(domain.owner),
        "dataProductCount": len(domain.data_products),
    }


def component_out(component: Component, *, include_spec: bool = True) -> dict:
    spec: dict[str, Any] = component.spec or {}
    contract = spec.get("dataContract") or {}
    out = {
        "id": component.id,
        "urn": component.urn,
        "name": component.name,
        "title": component.title or component.name,
        "kind": str(component.kind),
        "technology": component.technology,
        "description": component.description,
        "templateId": component.use_case_template_id,
        "platform": spec.get("platform", ""),
        "outputPortType": spec.get("outputPortType", ""),
        "tags": spec.get("tags", []),
        "endpoint": contract.get("endpoint", ""),
        "columnCount": len(contract.get("schema", []) or []),
        "hasPii": any(c.get("pii") for c in contract.get("schema", []) or []),
    }
    if include_spec:
        out["spec"] = spec
        out["dataContract"] = contract or None
    return out


def data_product_out(dp: DataProduct, *, extra: dict | None = None) -> dict:
    out = {
        "id": dp.id,
        "urn": dp.urn,
        "name": dp.name,
        "title": dp.title or dp.name,
        "description": dp.description,
        "domain": dp.domain.name,
        "domainTitle": dp.domain.title or dp.domain.name,
        "owner": user_out(dp.owner),
        "lifecycle": str(dp.lifecycle),
        "version": dp.version,
        "maturity": dp.maturity,
        "tags": dp.tags or [],
        "headCommit": dp.head_commit[:8] if dp.head_commit else "",
        "repoPath": dp.repo_path,
        "componentCount": len(dp.components),
        "outputPortCount": sum(1 for c in dp.components if c.kind == ComponentKind.OUTPUT_PORT),
        "publishedAt": dp.published_at,
        "createdAt": dp.created_at,
        "updatedAt": dp.updated_at,
    }
    if extra:
        out.update(extra)
    return out


def version_out(version: DataProductVersion) -> dict:
    return {
        "id": version.id,
        "version": version.version,
        "notes": version.notes,
        "commit": version.commit_sha[:8],
        "createdBy": user_out(version.created_by),
        "createdAt": version.created_at,
    }


def deployment_out(deployment: Deployment, *, include_logs: bool = False) -> dict:
    out = {
        "id": deployment.id,
        "environment": deployment.environment,
        "status": str(deployment.status),
        "operation": deployment.operation,
        "version": deployment.version_label,
        "requestedBy": user_out(deployment.requested_by),
        "startedAt": deployment.started_at,
        "finishedAt": deployment.finished_at,
        "outputs": deployment.outputs or {},
        "logLineCount": len(deployment.logs or []),
    }
    if include_logs:
        out["logs"] = deployment.logs or []
    return out


def policy_evaluation_out(evaluation: PolicyEvaluation) -> dict:
    return {
        "id": evaluation.id,
        "trigger": evaluation.trigger,
        "passed": evaluation.passed,
        "errorCount": evaluation.error_count,
        "warningCount": evaluation.warning_count,
        "findings": evaluation.results or [],
        "createdAt": evaluation.created_at,
    }


def access_request_out(request: AccessRequest) -> dict:
    return {
        "id": request.id,
        "status": str(request.status),
        "purpose": request.purpose,
        "consumerDataProduct": request.consumer_dp_urn,
        "decisionNote": request.decision_note,
        "requester": user_out(request.requester),
        "decidedBy": user_out(request.decided_by),
        "decidedAt": request.decided_at,
        "createdAt": request.created_at,
        "dataProduct": {
            "id": request.data_product.id,
            "urn": request.data_product.urn,
            "title": request.data_product.title,
            "domain": request.data_product.domain.name,
            "owner": user_out(request.data_product.owner),
        },
        "component": (
            {
                "id": request.component.id,
                "urn": request.component.urn,
                "name": request.component.name,
                "title": request.component.title,
                "technology": request.component.technology,
            }
            if request.component
            else None
        ),
    }


def event_out(event: Event) -> dict:
    return {
        "id": event.id,
        "type": event.type,
        "message": event.message,
        "actor": user_out(event.actor),
        "dataProduct": (
            {"id": event.data_product.id, "urn": event.data_product.urn, "title": event.data_product.title}
            if event.data_product
            else None
        ),
        "payload": event.payload or {},
        "createdAt": event.created_at,
    }


def commit_out(commit: CommitInfo) -> dict:
    return {
        "sha": commit.sha,
        "shortSha": commit.short_sha,
        "author": commit.author,
        "email": commit.email,
        "date": commit.date,
        "message": commit.message,
    }
