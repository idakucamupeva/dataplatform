"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, dataproducts, marketplace, platform, templates
from app.core.config import settings
from app.core.db import init_db
from app.services.dataproducts import LifecycleError
from app.services.descriptor_io import DescriptorError
from app.services.github import GitHubError
from app.services.marketplace import AccessError
from app.services.provisioning import ProvisioningError
from app.services.repository import GitError
from app.services.templates import TemplateError_

logger = logging.getLogger("dmp")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("%s ready — data directory %s", settings.platform_name, settings.data_dir)
    yield


app = FastAPI(
    title=f"{settings.platform_name} API",
    version="1.0.0",
    description=(
        "A self-service data mesh platform: scaffold a data product from a template, "
        "evolve its descriptor, let federated governance policies check it, provision it "
        "through technology adapters and publish it to the marketplace."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# domain errors -> HTTP
# --------------------------------------------------------------------------
def _problem(code: int, title: str, detail: str, extra: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": title, "detail": detail, **(extra or {})})


@app.exception_handler(DescriptorError)
async def _descriptor_error(_: Request, exc: DescriptorError):
    return _problem(
        status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid descriptor", exc.message, {"details": exc.details}
    )


@app.exception_handler(LifecycleError)
async def _lifecycle_error(_: Request, exc: LifecycleError):
    return _problem(status.HTTP_409_CONFLICT, "Lifecycle conflict", str(exc))


@app.exception_handler(TemplateError_)
async def _template_error(_: Request, exc: TemplateError_):
    return _problem(status.HTTP_400_BAD_REQUEST, "Template error", str(exc))


@app.exception_handler(ProvisioningError)
async def _provisioning_error(_: Request, exc: ProvisioningError):
    return _problem(
        status.HTTP_409_CONFLICT, "Provisioning refused", exc.message, {"details": exc.details}
    )


@app.exception_handler(AccessError)
async def _access_error(_: Request, exc: AccessError):
    return _problem(status.HTTP_409_CONFLICT, "Access request refused", str(exc))


@app.exception_handler(GitError)
async def _git_error(_: Request, exc: GitError):
    logger.exception("git operation failed")
    return _problem(status.HTTP_500_INTERNAL_SERVER_ERROR, "Repository error", str(exc))


@app.exception_handler(GitHubError)
async def _github_error(_: Request, exc: GitHubError):
    logger.error("GitHub call failed: %s", exc)
    return _problem(status.HTTP_502_BAD_GATEWAY, "GitHub error", str(exc))


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
API_PREFIX = "/api"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(templates.router, prefix=API_PREFIX)
app.include_router(dataproducts.router, prefix=API_PREFIX)
app.include_router(marketplace.router, prefix=API_PREFIX)
app.include_router(platform.router, prefix=API_PREFIX)


@app.get("/health", tags=["platform"])
def health() -> dict:
    return {"status": "ok", "platform": settings.platform_name}
