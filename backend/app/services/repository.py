"""Git-backed storage for data product repositories.

Every data product owns a repository.  The platform creates it on scaffolding,
commits every descriptor edit to it, and tags it on release.  A *bare* repo
under ``data/repos`` plays the role of the remote (the thing a real deployment
would host on GitHub/GitLab); a working copy under ``data/workspaces`` is what
the platform edits and pushes from.

Keeping real git underneath — rather than a `descriptor` column — is what gives
the platform version history, diffs, blame and release tags for free, and is
what makes "the repository is the source of truth" true rather than a slogan.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.config import settings


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

    def __init__(self, repos_dir: Path | None = None, workspaces_dir: Path | None = None) -> None:
        self.repos_dir = repos_dir or settings.repos_dir
        self.workspaces_dir = workspaces_dir or settings.workspaces_dir
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)

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
    ) -> str:
        """Initialise the remote + working copy and land the first commit."""
        remote = self.remote_path(slug)
        workspace = self.workspace_path(slug)
        if remote.exists() or workspace.exists():
            raise GitError(f"repository '{slug}' already exists")

        remote.parent.mkdir(parents=True, exist_ok=True)
        _run(["init", "--bare", "--initial-branch=main", str(remote)])
        _run(["init", "--initial-branch=main", str(workspace)])
        _run(["remote", "add", "origin", str(remote)], cwd=workspace)
        return self.commit(slug, files, author=author, email=email, message=message)

    def destroy(self, slug: str) -> None:
        shutil.rmtree(self.remote_path(slug), ignore_errors=True)
        shutil.rmtree(self.workspace_path(slug), ignore_errors=True)

    def exists(self, slug: str) -> bool:
        return self.remote_path(slug).exists()

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
        _run(["push", "--quiet", "origin", "main"], cwd=workspace)
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
        _run(["push", "--quiet", "origin", tag], cwd=workspace)

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
