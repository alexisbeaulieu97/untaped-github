"""Use cases: list GitHub repositories from org and team inventory scopes."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from untaped_github.application.ports import GithubRepoListService
from untaped_github.application.search import TeamScope
from untaped_github.domain import RepoListResult
from untaped_github.domain.repo_filters import compile_repo_pattern


@dataclass(frozen=True)
class RepoListFilters:
    """Local filters for repository inventory rows."""

    pattern: str | None = None
    regex: bool = False
    archived: bool | None = None
    fork: bool | None = None


class ListRepos:
    """List repository inventory from org/team scopes."""

    def __init__(self, repos: GithubRepoListService) -> None:
        self._repos = repos

    def __call__(
        self,
        filters: RepoListFilters,
        *,
        orgs: tuple[str, ...] = (),
        team_scopes: tuple[TeamScope, ...] = (),
    ) -> Iterator[RepoListResult]:
        rows = _collect_repos(self._repos, orgs=orgs, team_scopes=team_scopes)
        matcher = _compile_matcher(filters)
        filtered = (row for row in rows if _matches(row, filters=filters, matcher=matcher))
        deduped = {row.full_name: row for row in filtered}
        yield from sorted(deduped.values(), key=lambda row: row.full_name.casefold())


def _collect_repos(
    service: GithubRepoListService,
    *,
    orgs: tuple[str, ...],
    team_scopes: tuple[TeamScope, ...],
) -> Iterator[RepoListResult]:
    for org in orgs:
        for row in service.list_org_repos(org):
            yield RepoListResult.model_validate(row)
    for scope in team_scopes:
        for row in service.list_team_repos(scope.org, scope.slug):
            yield RepoListResult.model_validate(row)


def _matches(
    row: RepoListResult,
    *,
    filters: RepoListFilters,
    matcher: Callable[[RepoListResult], bool] | None,
) -> bool:
    if filters.archived is not None and row.archived is not filters.archived:
        return False
    if filters.fork is not None and row.fork is not filters.fork:
        return False
    return matcher(row) if matcher is not None else True


def _compile_matcher(filters: RepoListFilters) -> Callable[[RepoListResult], bool] | None:
    pattern = filters.pattern
    if not pattern:
        return None
    return compile_repo_pattern(pattern, regex=filters.regex)
