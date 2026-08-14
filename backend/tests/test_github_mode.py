"""GitHub mode, exercised without the network.

A fake client stands in for the GitHub API but hands out *real* local bare
repositories as clone URLs, so the whole flow — create remote, init workspace,
push, tag, destroy — runs through the exact same git plumbing that a real
GitHub remote would see. Only the HTTPS transport (and thus the auth header)
is out of scope here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.services.github import GitHubError
from app.services.repository import GitError, RepositoryService, _run

OWNER = "acme-data"


class FakeGitHub:
    """Implements the slice of GitHubClient that RepositoryService uses."""

    repo_prefix = "dmp-"
    private = True
    basic_auth = "ZmFrZQ=="  # never sent — clone URLs are local paths

    def __init__(self, root: Path) -> None:
        self.root = root
        self.created: list[str] = []
        self.deleted: list[str] = []

    def repo_name(self, slug: str) -> str:
        return f"{self.repo_prefix}{slug.replace('__', '-')}"

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.git"

    def repo_exists(self, name: str) -> bool:
        return self._path(name).exists()

    def create_repo(self, name: str, description: str = "") -> dict[str, str]:
        if self.repo_exists(name):
            raise GitHubError(f"repository '{OWNER}/{name}' already exists on GitHub")
        self._path(name).parent.mkdir(parents=True, exist_ok=True)
        _run(["init", "--bare", "--initial-branch=main", str(self._path(name))])
        self.created.append(name)
        return {
            "fullName": f"{OWNER}/{name}",
            "cloneUrl": str(self._path(name)),
            "htmlUrl": f"https://github.com/{OWNER}/{name}",
        }

    def delete_repo(self, name: str) -> bool:
        self.deleted.append(name)
        shutil.rmtree(self._path(name), ignore_errors=True)
        return True


@pytest.fixture
def hub(tmp_path) -> FakeGitHub:
    return FakeGitHub(tmp_path / "github")


@pytest.fixture
def repos(tmp_path, hub) -> RepositoryService:
    return RepositoryService(
        repos_dir=tmp_path / "repos",
        workspaces_dir=tmp_path / "workspaces",
        github_factory=lambda: hub,
    )


AUTHOR = {"author": "Alice Producer", "email": "alice@test.io"}


def test_scaffolding_creates_the_github_repository(repos, hub):
    sha = repos.create("sales__customer-360", {"README.md": "# C360\n"}, description="A view.", **AUTHOR)

    assert hub.created == ["dmp-sales-customer-360"]
    # the commit really landed on the remote, not just in the workspace
    remote_head = _run(
        ["--git-dir", str(hub._path("dmp-sales-customer-360")), "rev-parse", "HEAD"]
    ).strip()
    assert remote_head == sha
    # and the platform displays the GitHub URL, not a local path
    assert repos.remote_display("sales__customer-360") == "https://github.com/acme-data/dmp-sales-customer-360"


def test_the_token_is_not_written_into_the_workspace_config(repos, hub):
    repos.create("sales__customer-360", {"a.txt": "1"}, **AUTHOR)
    config = (repos.workspace_path("sales__customer-360") / ".git" / "config").read_text()
    assert hub.basic_auth not in config
    assert "extraheader" not in config.lower()


def test_commits_and_release_tags_reach_the_remote(repos, hub):
    repos.create("sales__customer-360", {"descriptor.yaml": "version: 1\n"}, **AUTHOR)
    sha = repos.commit(
        "sales__customer-360", {"descriptor.yaml": "version: 2\n"}, message="release: 1.0.0", **AUTHOR
    )
    repos.tag("sales__customer-360", "v1.0.0", "First release", **AUTHOR)

    bare = str(hub._path("dmp-sales-customer-360"))
    assert _run(["--git-dir", bare, "rev-parse", "main"]).strip() == sha
    assert "v1.0.0" in _run(["--git-dir", bare, "tag"])


def test_a_name_collision_on_github_aborts_cleanly(repos, hub):
    hub.create_repo("dmp-sales-customer-360")  # somebody already took the name
    with pytest.raises(GitHubError, match="already exists"):
        repos.create("sales__customer-360", {"a.txt": "1"}, **AUTHOR)
    # no half-created workspace left behind
    assert not repos.workspace_path("sales__customer-360").exists()


def test_a_failed_first_push_rolls_back_the_github_repository(repos, hub, monkeypatch):
    def broken_commit(*args, **kwargs):
        raise GitError("push rejected")

    monkeypatch.setattr(repos, "commit", broken_commit)
    with pytest.raises(GitError):
        repos.create("sales__orders", {"a.txt": "1"}, **AUTHOR)

    assert hub.deleted == ["dmp-sales-orders"]
    assert not repos.workspace_path("sales__orders").exists()


def test_destroy_deletes_the_github_repository(repos, hub):
    repos.create("sales__customer-360", {"a.txt": "1"}, **AUTHOR)
    repos.destroy("sales__customer-360")
    assert hub.deleted == ["dmp-sales-customer-360"]
    assert not repos.workspace_path("sales__customer-360").exists()


def test_exists_consults_github_when_nothing_is_local(repos, hub):
    hub.create_repo("dmp-sales-customer-360")
    assert repos.exists("sales__customer-360") is True
    assert repos.exists("sales__never-created") is False
