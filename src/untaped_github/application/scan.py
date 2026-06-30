"""Use cases for local Git corpus sync and scan workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from untaped.api import UntapedError

from untaped_github._concurrency import bounded_map
from untaped_github.application.inventory import (
    RepositoryInventoryItem,
    RepositoryInventoryScope,
    ResolveRepositoryInventory,
)
from untaped_github.application.ports import GitCorpus, GithubRepositoryInventoryService
from untaped_github.domain import (
    CodeHitResult,
    CorpusFailure,
    CorpusRepoResult,
    CorpusRepoTarget,
    WorktreeResult,
)
from untaped_github.domain.errors import GitCorpusError


@dataclass(frozen=True)
class SyncOptions:
    """Options for refreshing the local corpus."""

    root: Path
    depth: int = 1
    parallel: int = 8
    auth_header: str | None = None

    def __post_init__(self) -> None:
        if self.depth < 0:
            raise ValueError("depth must be non-negative")
        if self.parallel < 1:
            raise ValueError("parallel must be positive")


@dataclass(frozen=True)
class GrepOptions:
    """Options for local corpus grep."""

    root: Path
    pattern: str
    sync: bool = False
    paths: tuple[str, ...] = ()
    globs: tuple[str, ...] = ()
    ignore_case: bool = False
    fixed_strings: bool = False
    word_regexp: bool = False
    depth: int = 1
    parallel: int = 8
    auth_header: str | None = None

    def __post_init__(self) -> None:
        if self.depth < 0:
            raise ValueError("depth must be non-negative")
        if self.parallel < 1:
            raise ValueError("parallel must be positive")


@dataclass(frozen=True)
class SyncResult:
    """Result of a corpus sync."""

    rows: tuple[CorpusRepoResult, ...]
    failures: tuple[CorpusFailure, ...]


@dataclass(frozen=True)
class GrepResult:
    """Result of a local corpus grep."""

    rows: tuple[CodeHitResult, ...]
    failures: tuple[CorpusFailure, ...]


class SyncCorpus:
    """Refresh the local corpus for repository inventory scopes."""

    def __init__(self, inventory: GithubRepositoryInventoryService, corpus: GitCorpus) -> None:
        self._inventory = inventory
        self._corpus = corpus

    def __call__(self, scope: RepositoryInventoryScope, options: SyncOptions) -> SyncResult:
        repos = _targets(ResolveRepositoryInventory(self._inventory)(scope))
        return _sync_repos(self._corpus, repos, options)


class GrepCorpus:
    """Search default branches in the local corpus."""

    def __init__(self, inventory: GithubRepositoryInventoryService, corpus: GitCorpus) -> None:
        self._inventory = inventory
        self._corpus = corpus

    def __call__(self, scope: RepositoryInventoryScope, options: GrepOptions) -> GrepResult:
        repos = _targets(ResolveRepositoryInventory(self._inventory)(scope))
        failures: list[CorpusFailure] = []
        failed_repos: set[str] = set()
        if options.sync:
            sync_result = _sync_repos(
                self._corpus,
                repos,
                SyncOptions(
                    root=options.root,
                    depth=options.depth,
                    parallel=options.parallel,
                    auth_header=options.auth_header,
                ),
            )
            failures.extend(sync_result.failures)
            failed_repos.update(failure.repo for failure in sync_result.failures)

        rows: list[CodeHitResult] = []

        def grep_one(repo: CorpusRepoTarget) -> tuple[CodeHitResult, ...] | CorpusFailure:
            if repo.full_name in failed_repos:
                return ()
            if not self._corpus.has_default_branch(repo, root=options.root):
                return CorpusFailure(
                    repo=repo.full_name,
                    reason=(
                        "repository is not in the local corpus; "
                        "run `untaped-github scan grep --sync`"
                    ),
                )
            try:
                return self._corpus.grep_default_branch(
                    repo,
                    root=options.root,
                    pattern=options.pattern,
                    paths=options.paths,
                    globs=options.globs,
                    ignore_case=options.ignore_case,
                    fixed_strings=options.fixed_strings,
                    word_regexp=options.word_regexp,
                )
            except GitCorpusError as exc:
                return CorpusFailure(repo=repo.full_name, reason=str(exc))

        def record(
            _repo: CorpusRepoTarget,
            outcome: tuple[CodeHitResult, ...] | CorpusFailure,
        ) -> None:
            if isinstance(outcome, CorpusFailure):
                failures.append(outcome)
            else:
                rows.extend(outcome)

        bounded_map(grep_one, repos, concurrency=options.parallel, on_each=record)
        return GrepResult(rows=tuple(rows), failures=tuple(failures))


class ListCorpus:
    """List repositories cached in the local corpus."""

    def __init__(self, corpus: GitCorpus) -> None:
        self._corpus = corpus

    def __call__(self, *, root: Path) -> tuple[CorpusRepoResult, ...]:
        return self._corpus.list_repos(root=root)


class CleanCorpus:
    """Remove repositories from the managed local corpus."""

    def __init__(self, corpus: GitCorpus) -> None:
        self._corpus = corpus

    def __call__(self, *, root: Path, repos: tuple[str, ...]) -> tuple[CorpusRepoResult, ...]:
        return self._corpus.clean_repos(root=root, repos=repos)


class WorktreeCorpus:
    """Materialize one cached repository ref as a worktree."""

    def __init__(self, corpus: GitCorpus) -> None:
        self._corpus = corpus

    def __call__(self, repo: str, *, root: Path, ref: str | None) -> WorktreeResult:
        owner, separator, name = repo.partition("/")
        if not owner or not separator or not name or "/" in name:
            raise UntapedError(f"repository must be owner/name: {repo!r}")
        item = self._corpus.get_repo(root=root, repo=repo)
        if item is None:
            raise GitCorpusError(
                "repository is not in the local corpus; run `untaped-github scan sync`"
            )
        return self._corpus.materialize_worktree(item, root=root, ref=ref)


def _sync_repos(
    corpus: GitCorpus,
    repos: tuple[CorpusRepoTarget, ...],
    options: SyncOptions,
) -> SyncResult:
    rows: list[CorpusRepoResult] = []
    failures: list[CorpusFailure] = []

    def sync_one(repo: CorpusRepoTarget) -> CorpusRepoResult | CorpusFailure:
        try:
            return corpus.sync_default_branch(
                repo,
                root=options.root,
                depth=options.depth,
                auth_header=options.auth_header,
            )
        except GitCorpusError as exc:
            return CorpusFailure(repo=repo.full_name, reason=str(exc))

    def record(
        _repo: CorpusRepoTarget,
        outcome: CorpusRepoResult | CorpusFailure,
    ) -> None:
        if isinstance(outcome, CorpusFailure):
            failures.append(outcome)
        else:
            rows.append(outcome)

    bounded_map(sync_one, repos, concurrency=options.parallel, on_each=record)
    return SyncResult(rows=tuple(rows), failures=tuple(failures))


def _targets(items: tuple[RepositoryInventoryItem, ...]) -> tuple[CorpusRepoTarget, ...]:
    return tuple(_target(item) for item in items)


def _target(item: RepositoryInventoryItem) -> CorpusRepoTarget:
    return CorpusRepoTarget(
        full_name=item.full_name,
        default_branch=item.default_branch,
        clone_url=item.clone_url,
        html_url=item.html_url,
    )
