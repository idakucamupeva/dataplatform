from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Domain
from app.services.templates import TemplateError_, template_registry

router = APIRouter(prefix="/templates", tags=["scaffolder"])


@router.get("")
def list_templates(
    db: DbSession,
    _: CurrentUser,
    type: str | None = Query(default=None, description="dataproduct | component"),
    kind: str | None = Query(default=None, description="outputport | storage | workload | observability"),
) -> list[dict]:
    return [t.as_summary() for t in template_registry.all(type_=type, kind=kind)]


@router.get("/{template_id}")
def get_template(template_id: str, db: DbSession, _: CurrentUser) -> dict:
    try:
        template = template_registry.get(template_id)
    except TemplateError_ as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    detail = template.as_detail()
    # Resolve dynamic option sources so the client can render the form directly.
    domains = [
        {"value": d.name, "label": d.title or d.name}
        for d in db.execute(select(Domain).order_by(Domain.name)).scalars()
    ]
    for section in detail["parameters"]:
        for field in section.get("fields", []):
            if field.get("optionsFrom") == "domains":
                field["options"] = domains
    return detail


@router.post("/reload", status_code=status.HTTP_204_NO_CONTENT)
def reload_templates(_: CurrentUser) -> None:
    """Pick up template files edited on disk without restarting the server."""
    template_registry.reload()
