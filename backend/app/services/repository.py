"""Git-backed storage for data product repositories.

Every data product owns a repository.  The platform creates it on scaffolding,
commits every descriptor edit to it, and tags it on release.  A working copy
under ``data/workspaces`` is what the platform edits and pushes from; the
remote is one of two things:

* **GitHub mode** — when a token is configured (:mod:`app.services.github`),
  scaffolding creates a real repository under the configured user/organisation
  and every commit and tag is pushed there.
* **Local mode** — without a token, a *bare* repo under ``data/repos`` plays
  the role of the remote, so the platform works offline and in tests.

Keeping real git underneath — rather than a `descriptor` column — is what gives
the platform version history, diffs, blame and release tags for free, and is
what makes "the repository is the source of truth" true rather than a slogan.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.services import github
from app.services.github import GitHubClient, GitHubError


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    short_sha: str
    author: str
    email: str
    date: datetime
    message: str


def _run(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


class RepositoryService:
    """Thin, testable wrapper over the handful of git operations we need."""

    def __init__(
        self,
        repos_dir: Path | None = None,
        workspaces_dir: Path | None = None,
        github_factory: Callable[[], GitHubClient | None] | None = None,
    ) -> None:
        self.repos_dir = repos_dir or settings.repos_dir
        self.workspaces_dir = workspaces_dir or settings.workspaces_dir
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        # resolved per call, so seed --local / tests can flip modes at runtime
        self._github = github_factory or github.get_client

    # -- naming ------------------------------------------------------------
    def slug(self, domain: str, name: str) -> str:
        return f"{domain}__{name}"

    def remote_path(self, slug: str) -> Path:
        return self.repos_dir / f"{slug}.git"

    def workspace_path(self, slug: str) -> Path:
        return self.workspaces_dir / slug

    # -- lifecycle ---------------------------------------------------------
    def create(
        self,
        slug: str,
        files: dict[str, str],
        *,
        author: str,
        email: str,
        message: str = "chore: scaffold data product",
        description: str = "",
    ) -> str:
        """Create the remote (GitHub or local bare), init the working copy and
        land the first commit."""
        workspace = self.workspace_path(slug)
        if workspace.exists():
            raise GitError(f"repository '{slug}' already exists")

        client = self._github()
        if client is None:
            remote = self.remote_path(slug)
            if remote.exists():
                raise GitError(f"repository '{slug}' already exists")
            remote.parent.mkdir(parents=True, exist_ok=True)
            _run(["init", "--bare", "--initial-branch=main", str(remote)])
            origin, html_url = str(remote), ""
        else:
            repo = client.create_repo(client.repo_name(slug), description=description)
            origin, html_url = repo["cloneUrl"], repo["htmlUrl"]

        try:
            _run(["init", "--initial-branch=main", str(workspace)])
            _run(["remote", "add", "origin", origin], cwd=workspace)
            if html_url:
                # remembered for display; the token itself is never written here
                _run(["config", "dmp.htmlUrl", html_url], cwd=workspace)
            return self.commit(slug, files, author=author, email=email, message=message)
        except Exception:
            # never leave a half-created repository behind
            shutil.rmtree(workspace, ignore_errors=True)
            if client is None:
                shutil.rmtree(self.remote_path(slug), ignore_errors=True)
            else:
                with contextlib.suppress(GitHubError):
                    client.delete_repo(client.repo_name(slug))
            raise

    def destroy(self, slug: str) -> None:
        client = self._github()
        if client is not None and self._origin_is_remote(slug):
            # best effort: needs the delete_repo scope; a failure is logged,
            # not raised, so the catalog entry can still be removed
            with contextlib.suppress(GitHubError):
                client.delete_repo(client.repo_name(slug))
        shutil.rmtree(self.remote_path(slug), ignore_errors=True)
        shutil.rmtree(self.workspace_path(slug), ignore_errors=True)

    def exists(self, slug: str) -> bool:
        if self.workspace_path(slug).exists() or self.remote_path(slug).exists():
            return True
        client = self._github()
        return client is not None and client.repo_exists(client.repo_name(slug))

    def remote_display(self, slug: str) -> str:
        """What to show as the repository's location: the GitHub URL when the
        product lives there, the local bare path otherwise."""
        workspace = self.workspace_path(slug)
        if workspace.exists():
            with contextlib.suppress(GitError):
                url = _run(["config", "--get", "dmp.htmlUrl"], cwd=workspace).strip()
                if url:
                    return url
        return str(self.remote_path(slug))

    def _origin_is_remote(self, slug: str) -> bool:
        workspace = self.workspace_path(slug)
        if not workspace.exists():
            # workspace already gone: only GitHub can tell whether the repo exists
            client = self._github()
            return client is not None and client.repo_exists(client.repo_name(slug))
        # `dmp.htmlUrl` is written exactly when the repo was created on GitHub
        with contextlib.suppress(GitError):
            return bool(_run(["config", "--get", "dmp.htmlUrl"], cwd=workspace).strip())
        return False

    def _net_args(self, workspace: Path) -> list[str]:
        """Per-invocation auth for pushes to an https remote — keeps the token
        out of every on-disk git config."""
        with contextlib.suppress(GitError):
            url = _run(["remote", "get-url", "origin"], cwd=workspace).strip()
            if url.startswith("http"):
                client = self._github()
                if client is not None:
                    return ["-c", f"http.extraheader=Authorization: Basic {client.basic_auth}"]
        return []

    # -- content -----------------------------------------------------------
    def commit(
        self,
        slug: str,
        files: dict[str, str],
        *,
        author: str,
        email: str,
        message: str,
    ) -> str:
        workspace = self._require_workspace(slug)
        for relative, content in files.items():
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            _run(["add", "--", relative], cwd=workspace)

        if not _run(["status", "--porcelain"], cwd=workspace).strip():
            return self.head(slug)

        _run(
            [
                "-c", f"user.name={author}",
                "-c", f"user.email={email}",
                "commit", "-m", message,
            ],
            cwd=workspace,
        )
        _run([*self._net_args(workspace), "push", "--quiet", "origin", "main"], cwd=workspace)
        return self.head(slug)

    def read(self, slug: str, path: str, ref: str = "HEAD") -> str:
        workspace = self._require_workspace(slug)
        try:
            return _run(["show", f"{ref}:{path}"], cwd=workspace)
        except GitError as exc:
            raise FileNotFoundError(f"{path} not found at {ref}") from exc

    def list_files(self, slug: str, ref: str = "HEAD") -> list[str]:
        workspace = self._require_workspace(slug)
        out = _run(["ls-tree", "-r", "--name-only", ref], cwd=workspace)
        return [line for line in out.splitlines() if line]

    def head(self, slug: str) -> str:
        return _run(["rev-parse", "HEAD"], cwd=self._require_workspace(slug)).strip()

    def log(self, slug: str, path: str | None = None, limit: int = 50) -> list[CommitInfo]:
        workspace = self._require_workspace(slug)
        fmt = "%H%x1f%an%x1f%ae%x1f%aI%x1f%s"
        args = ["log", f"--max-count={limit}", f"--pretty=format:{fmt}"]
        if path:
            args += ["--", path]
        raw = _run(args, cwd=workspace)
        commits: list[CommitInfo] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            sha, author, email, date, subject = line.split("\x1f")
            commits.append(
                CommitInfo(
                    sha=sha,
                    short_sha=sha[:8],
                    author=author,
                    email=email,
                    date=datetime.fromisoformat(date),
                    message=subject,
                )
            )
        return commits

    def diff(self, slug: str, ref_a: str, ref_b: str = "HEAD", path: str | None = None) -> str:
        workspace = self._require_workspace(slug)
        args = ["diff", "--unified=3", ref_a, ref_b]
        if path:
            args += ["--", path]
        return _run(args, cwd=workspace)

    def tag(self, slug: str, tag: str, message: str, *, author: str, email: str) -> None:
        workspace = self._require_workspace(slug)
        _run(
            [
                "-c", f"user.name={author}",
                "-c", f"user.email={email}",
                "tag", "-a", tag, "-m", message,
            ],
            cwd=workspace,
        )
        _run([*self._net_args(workspace), "push", "--quiet", "origin", tag], cwd=workspace)

    def tags(self, slug: str) -> list[str]:
        out = _run(["tag", "--sort=-creatordate"], cwd=self._require_workspace(slug))
        return [t for t in out.splitlines() if t]

    # -- internals ---------------------------------------------------------
    def _require_workspace(self, slug: str) -> Path:
        workspace = self.workspace_path(slug)
        if not workspace.exists():
            raise GitError(f"workspace for '{slug}' does not exist")
        return workspace


repository_service = RepositoryService()
