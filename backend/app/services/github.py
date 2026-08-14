"""GitHub integration.

When ``DMP_GITHUB_TOKEN`` (or ``GITHUB_TOKEN``) is set, the platform creates a
real GitHub repository for every scaffolded data product and pushes each
descriptor commit and release tag to it.  This module is the only place that
talks to the GitHub REST API; :mod:`app.services.repository` stays a git
wrapper and merely asks this client where "origin" should point.

The token never lands on disk: the remote URL stored in the workspace is the
plain ``https://github.com/...`` clone URL, and pushes authenticate through a
per-invocation ``http.extraheader`` instead.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("dmp.github")


class GitHubError(RuntimeError):
    """A GitHub API call failed or was refused."""


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        api_url: str = "https://api.github.com",
        owner: str = "",
        repo_prefix: str = "dmp-",
        private: bool = True,
    ) -> None:
        self.token = token
        self.owner_setting = owner
        self.repo_prefix = repo_prefix
        self.private = private
        self._http = httpx.Client(
            base_url=api_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "datamesh-platform",
            },
            timeout=30.0,
        )
        self._login: str | None = None

    # -- plumbing ----------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubError(f"cannot reach GitHub: {exc}") from exc

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            message = body.get("message", "")
            errors = "; ".join(
                e.get("message", str(e)) for e in body.get("errors", []) if e
            )
            return " — ".join(part for part in (message, errors) if part)
        except Exception:  # noqa: BLE001 - non-JSON error body
            return response.text[:200]

    def _json_or_error(self, response: httpx.Response, action: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise GitHubError(f"{action} failed ({response.status_code}): {self._detail(response)}")
        return response.json()

    # -- identity ----------------------------------------------------------
    @property
    def login(self) -> str:
        """The user the token belongs to (one API call, cached)."""
        if self._login is None:
            data = self._json_or_error(self._request("GET", "/user"), "reading the token's user")
            self._login = data["login"]
        return self._login

    @property
    def owner(self) -> str:
        return self.owner_setting or self.login

    @property
    def basic_auth(self) -> str:
        """Value for git's ``Authorization: Basic`` header when pushing."""
        return base64.b64encode(f"x-access-token:{self.token}".encode()).decode()

    def repo_name(self, slug: str) -> str:
        """`sales__customer-360` -> `dmp-sales-customer-360`."""
        return f"{self.repo_prefix}{slug.replace('__', '-')}"

    # -- repositories ------------------------------------------------------
    def repo_exists(self, name: str) -> bool:
        return self._request("GET", f"/repos/{self.owner}/{name}").status_code == 200

    def create_repo(self, name: str, description: str = "") -> dict[str, str]:
        payload = {
            "name": name,
            "description": (description or "").replace("\n", " ").strip()[:350],
            "private": self.private,
            "auto_init": False,
            "has_issues": True,
            "has_projects": False,
            "has_wiki": False,
        }
        if self.owner_setting and self.owner_setting != self.login:
            response = self._request("POST", f"/orgs/{self.owner_setting}/repos", json=payload)
        else:
            response = self._request("POST", "/user/repos", json=payload)
        if response.status_code == 422:
            raise GitHubError(
                f"repository '{self.owner}/{name}' already exists on GitHub "
                f"({self._detail(response)})"
            )
        data = self._json_or_error(response, f"creating repository '{name}'")
        return {
            "fullName": data["full_name"],
            "cloneUrl": data["clone_url"],
            "htmlUrl": data["html_url"],
        }

    def delete_repo(self, name: str) -> bool:
        """Best-effort delete; needs the `delete_repo` scope."""
        response = self._request("DELETE", f"/repos/{self.owner}/{name}")
        if response.status_code == 204:
            return True
        logger.warning(
            "could not delete GitHub repository %s/%s (%s): %s",
            self.owner, name, response.status_code, self._detail(response),
        )
        return False

    def status(self) -> dict[str, Any]:
        """Token health, for the platform status endpoint."""
        response = self._request("GET", "/user")
        data = self._json_or_error(response, "checking the token")
        return {
            "login": data["login"],
            "owner": self.owner_setting or data["login"],
            "scopes": [s for s in response.headers.get("x-oauth-scopes", "").split(", ") if s],
            "repoPrefix": self.repo_prefix,
            "private": self.private,
        }


# --------------------------------------------------------------------------
# module-level accessor
# --------------------------------------------------------------------------
_cached: GitHubClient | None = None
_disabled = False


def disable() -> None:
    """Force local mode for this process (used by `seed --local` and tests)."""
    global _disabled
    _disabled = True


def get_client() -> GitHubClient | None:
    """The configured client, or ``None`` when GitHub mode is off."""
    global _cached
    if _disabled or not settings.github_token:
        return None
    if _cached is None:
        _cached = GitHubClient(
            settings.github_token,
            api_url=settings.github_api_url,
            owner=settings.github_owner,
            repo_prefix=settings.github_repo_prefix,
            private=settings.github_repos_private,
        )
    return _cached
