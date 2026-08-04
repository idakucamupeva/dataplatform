"""The git-backed store: history, tags and immutability of past revisions."""

from __future__ import annotations

import pytest

from app.services.repository import GitError, RepositoryService

AUTHOR = {"author": "Alice Producer", "email": "alice@test.io"}


@pytest.fixture
def repos(tmp_path) -> RepositoryService:
    return RepositoryService(repos_dir=tmp_path / "repos", workspaces_dir=tmp_path / "workspaces")


def test_creating_a_repository_lands_the_first_commit(repos: RepositoryService):
    sha = repos.create("sales__orders", {"README.md": "# Orders\n"}, **AUTHOR)
    assert len(sha) == 40
    assert repos.read("sales__orders", "README.md") == "# Orders\n"
    assert repos.list_files("sales__orders") == ["README.md"]


def test_the_same_repository_cannot_be_created_twice(repos: RepositoryService):
    repos.create("sales__orders", {"a.txt": "1"}, **AUTHOR)
    with pytest.raises(GitError):
        repos.create("sales__orders", {"a.txt": "1"}, **AUTHOR)


def test_history_is_kept_and_past_revisions_stay_readable(repos: RepositoryService):
    first = repos.create("sales__orders", {"descriptor.yaml": "version: 1\n"}, **AUTHOR)
    second = repos.commit(
        "sales__orders", {"descriptor.yaml": "version: 2\n"}, message="feat: bump", **AUTHOR
    )

    assert repos.read("sales__orders", "descriptor.yaml", ref=first) == "version: 1\n"
    assert repos.read("sales__orders", "descriptor.yaml", ref=second) == "version: 2\n"

    log = repos.log("sales__orders")
    assert [commit.message for commit in log] == ["feat: bump", "chore: scaffold data product"]
    assert log[0].author == "Alice Producer"


def test_committing_nothing_new_does_not_create_a_commit(repos: RepositoryService):
    first = repos.create("sales__orders", {"a.txt": "same"}, **AUTHOR)
    again = repos.commit("sales__orders", {"a.txt": "same"}, message="noop", **AUTHOR)
    assert first == again
    assert len(repos.log("sales__orders")) == 1


def test_a_release_tag_is_recorded(repos: RepositoryService):
    repos.create("sales__orders", {"a.txt": "1"}, **AUTHOR)
    repos.tag("sales__orders", "v1.0.0", "First release", **AUTHOR)
    assert repos.tags("sales__orders") == ["v1.0.0"]


def test_diffs_are_available_between_revisions(repos: RepositoryService):
    first = repos.create("sales__orders", {"a.txt": "one\n"}, **AUTHOR)
    repos.commit("sales__orders", {"a.txt": "two\n"}, message="change", **AUTHOR)
    diff = repos.diff("sales__orders", first)
    assert "-one" in diff and "+two" in diff


def test_reading_a_missing_file_raises(repos: RepositoryService):
    repos.create("sales__orders", {"a.txt": "1"}, **AUTHOR)
    with pytest.raises(FileNotFoundError):
        repos.read("sales__orders", "nope.txt")
