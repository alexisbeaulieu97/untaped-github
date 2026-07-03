"""Unit tests for local corpus sync and grep use cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from untaped_github.application import RepositoryInventoryScope, TeamScope
from untaped_github.application.scan import (
    CleanCorpus,
    GrepCorpus,
    GrepOptions,
    ListCorpus,
    SyncCorpus,
    SyncOptions,
    WorktreeCorpus,
)
from untaped_github.domain import CodeHitResult, CorpusFailure, CorpusRepoResult, WorktreeResult
from untaped_github.domain.errors import GitCorpusError


def _repo(full_name: str, *, clone_url: str | None = None) -> dict[str, object]:
    name = full_name.rsplit("/", 1)[1]
    return {
        "full_name": full_name,
        "name": name,
        "html_url": f"https://github.com/{full_name}",
        "clone_url": clone_url or f"https://github.com/{full_name}.git",
        "ssh_url": f"git@github.com:{full_name}.git",
        "default_branch": "main",
        "private": True,
        "archived": False,
        "fork": False,
    }


class _Inventory:
    def __init__(self) -> None:
        self.orgs: list[str] = []
        self.teams: list[tuple[str, str]] = []
        self.repos: list[tuple[str, str]] = []

    def list_org_repos(self, org: str) -> list[dict[str, object]]:
        self.orgs.append(org)
        return [_repo(f"{org}/api")]

    def list_team_repos(self, org: str, team_slug: str) -> list[dict[str, object]]:
        self.teams.append((org, team_slug))
        return [_repo(f"{org}/worker"), _repo(f"{org}/api")]

    def get_repository(self, owner: str, repo: str) -> dict[str, object]:
        self.repos.append((owner, repo))
        return _repo(f"{owner}/{repo}")


class _Corpus:
    def __init__(self, *, fail: set[str] | None = None, cached: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.cached = cached or set()
        self.synced: list[str] = []
        self.greped: list[str] = []

    def sync_default_branch(
        self,
        repo: object,
        *,
        root: Path,
        depth: int,
        auth_header: str | None,
    ) -> CorpusRepoResult:
        full_name = repo.full_name  # type: ignore[attr-defined]
        self.synced.append(full_name)
        if full_name in self.fail:
            raise GitCorpusError("fetch denied")
        self.cached.add(full_name)
        return CorpusRepoResult(
            repo=full_name,
            ref=repo.default_branch,  # type: ignore[attr-defined]
            path=str(root / full_name.replace("/", "__")),
            clone_url=repo.clone_url,  # type: ignore[attr-defined]
            status="synced",
        )

    def has_default_branch(self, repo: object, *, root: Path) -> bool:
        return repo.full_name in self.cached  # type: ignore[attr-defined]

    def grep_default_branch(
        self,
        repo: object,
        *,
        root: Path,
        pattern: str,
        paths: tuple[str, ...],
        globs: tuple[str, ...],
        ignore_case: bool,
        fixed_strings: bool,
        word_regexp: bool,
    ) -> tuple[CodeHitResult, ...]:
        full_name = repo.full_name  # type: ignore[attr-defined]
        self.greped.append(full_name)
        if full_name in self.fail:
            raise GitCorpusError("grep failed")
        return (
            CodeHitResult(
                repo=full_name,
                ref=repo.default_branch,  # type: ignore[attr-defined]
                path="playbook.yml",
                line=2,
                column=7,
                text=f"uses: {pattern}",
            ),
        )

    def list_repos(self, *, root: Path) -> tuple[CorpusRepoResult, ...]:
        return tuple(
            CorpusRepoResult(repo=name, ref="main", path=str(root / name), status="cached")
            for name in sorted(self.cached)
        )

    def get_repo(self, *, root: Path, repo: str) -> object | None:
        if repo not in self.cached:
            return None
        return type(
            "Repo",
            (),
            {
                "full_name": repo,
                "default_branch": "main",
                "clone_url": f"https://github.com/{repo}.git",
                "html_url": f"https://github.com/{repo}",
            },
        )()

    def clean_repo(self, *, root: Path, repo: CorpusRepoResult) -> CorpusRepoResult:
        self.cached.discard(repo.repo)
        return repo.model_copy(update={"status": "removed"})

    def materialize_worktree(
        self,
        repo: object,
        *,
        root: Path,
        ref: str | None,
    ) -> WorktreeResult:
        return WorktreeResult(
            repo=repo.full_name,  # type: ignore[attr-defined]
            ref=ref or repo.default_branch,  # type: ignore[attr-defined]
            path=str(root / "worktrees" / repo.full_name.replace("/", "__")),  # type: ignore[attr-defined]
        )


def test_sync_corpus_expands_scopes_dedupes_and_collects_partial_failures(
    tmp_path: Path,
) -> None:
    inventory = _Inventory()
    corpus = _Corpus(fail={"acme/worker"})

    result = SyncCorpus(inventory, corpus)(
        RepositoryInventoryScope(
            orgs=("acme",),
            teams=(TeamScope(org="acme", slug="backend"),),
            repos=("acme/tools",),
        ),
        SyncOptions(root=tmp_path / "corpus", parallel=1),
    )

    assert [row.repo for row in result.rows] == ["acme/api", "acme/tools"]
    assert result.failures == (CorpusFailure(repo="acme/worker", reason="fetch denied"),)
    assert corpus.synced == ["acme/api", "acme/tools", "acme/worker"]


def test_grep_corpus_requires_cached_repos_unless_syncing(tmp_path: Path) -> None:
    result = GrepCorpus(_Inventory(), _Corpus())(
        RepositoryInventoryScope(orgs=("acme",)),
        GrepOptions(root=tmp_path / "corpus", pattern="acme/action", sync=False, parallel=1),
    )

    assert result.rows == ()
    assert result.failures == (
        CorpusFailure(
            repo="acme/api",
            reason="repository is not in the local corpus; run `untaped-github scan grep --sync`",
        ),
    )


def test_grep_corpus_syncs_first_when_requested(tmp_path: Path) -> None:
    corpus = _Corpus()

    result = GrepCorpus(_Inventory(), corpus)(
        RepositoryInventoryScope(orgs=("acme",)),
        GrepOptions(root=tmp_path / "corpus", pattern="acme/action", sync=True, parallel=1),
    )

    assert [row.repo for row in result.rows] == ["acme/api"]
    assert result.failures == ()
    assert corpus.synced == ["acme/api"]
    assert corpus.greped == ["acme/api"]


def test_list_clean_and_worktree_delegate_to_corpus(tmp_path: Path) -> None:
    corpus = _Corpus(cached={"acme/api", "acme/worker"})

    listed = ListCorpus(corpus)(root=tmp_path / "corpus")
    cleaned = CleanCorpus(corpus)(root=tmp_path / "corpus", repo=listed[0])
    worktree = WorktreeCorpus(corpus)(
        "acme/worker",
        root=tmp_path / "corpus",
        ref="main",
    )

    assert [row.repo for row in listed] == ["acme/api", "acme/worker"]
    assert cleaned.repo == "acme/api"
    assert worktree == WorktreeResult(
        repo="acme/worker",
        ref="main",
        path=str(tmp_path / "corpus" / "worktrees" / "acme__worker"),
    )


def test_worktree_uses_cached_metadata_without_inventory(tmp_path: Path) -> None:
    corpus = _Corpus(cached={"acme/worker"})

    worktree = WorktreeCorpus(corpus)(
        "acme/worker",
        root=tmp_path / "corpus",
        ref=None,
    )

    assert worktree.repo == "acme/worker"
    assert worktree.ref == "main"


def test_worktree_missing_cached_repo_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(GitCorpusError, match="scan sync"):
        WorktreeCorpus(_Corpus())("acme/missing", root=tmp_path / "corpus", ref=None)


def test_parallel_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="parallel"):
        SyncOptions(root=tmp_path, parallel=0)
