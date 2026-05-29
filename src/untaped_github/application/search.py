"""Use cases: search GitHub for repos, code, issues, and users."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import islice
from typing import Any

from pydantic import BaseModel

from untaped_github.application.ports import GithubSearchService, GithubTeamService
from untaped_github.domain import (
    CodeResult,
    CodeSearchFilters,
    IssueResult,
    IssueSearchFilters,
    RepoResult,
    RepoSearchFilters,
    ScopedQueryBase,
    UserResult,
    UserSearchFilters,
)

WarnFn = Callable[[str], None]

# Team expansion is generated, not user-authored, so keep the automatic
# OR group small. Six short repo qualifiers render below GitHub's 256-char
# query budget while still covering the common "backend owns a few repos"
# case; users can pass explicit --repo values when they need a wider query.
MAX_TEAM_REPO_QUALIFIERS = 6


@dataclass(frozen=True)
class TeamScope:
    """A GitHub team scoped by owning organization."""

    org: str
    slug: str


def _noop(_: str) -> None:
    pass


def _resolve_team_repos(
    teams: GithubTeamService,
    *,
    team_scopes: tuple[TeamScope, ...],
    warn: WarnFn,
) -> tuple[str, ...]:
    """Pre-resolve team scopes into ``owner/name`` repo strings.

    Bounded at ``MAX_TEAM_REPO_QUALIFIERS + 1`` so a 5k-repo team doesn't
    drag every page over the wire just to be truncated.
    """
    cap = MAX_TEAM_REPO_QUALIFIERS + 1
    all_repos: list[str] = []
    for scope in team_scopes:
        repos: list[str] = []
        for entry in islice(teams.list_team_repos(scope.org, scope.slug), cap):
            full_name = entry.get("full_name")
            if isinstance(full_name, str) and full_name:
                repos.append(full_name)
        if len(repos) > MAX_TEAM_REPO_QUALIFIERS:
            warn(
                f"team {scope.org}/{scope.slug} has more than {MAX_TEAM_REPO_QUALIFIERS} repos; "
                "truncating to stay under GitHub's query length limit"
            )
            repos = repos[:MAX_TEAM_REPO_QUALIFIERS]
        all_repos.extend(repos)
    return tuple(all_repos)


def _apply_scope_defaults[F: ScopedQueryBase](filters: F, team_repos: tuple[str, ...]) -> F:
    """Merge team-resolved repos and inject ``user:@me`` when no scope set."""
    repos = (*filters.repos, *team_repos)
    has_scope = bool(filters.user or filters.orgs or repos)
    overrides: dict[str, object] = {"repos": repos}
    if not has_scope:
        overrides["user"] = "@me"
    return filters.model_copy(update=overrides)


_SearchMethod = Callable[..., Iterator[dict[str, Any]]]


def _run_scoped_search[F: ScopedQueryBase, R: BaseModel](
    search_method: _SearchMethod,
    result_cls: type[R],
    teams: GithubTeamService,
    filters: F,
    *,
    team_scopes: tuple[TeamScope, ...],
    warn: WarnFn,
) -> Iterator[R]:
    team_repos = _resolve_team_repos(teams, team_scopes=team_scopes, warn=warn)
    effective = _apply_scope_defaults(filters, team_repos)
    q = effective.to_query_string()
    for row in search_method(q, sort=effective.sort, limit=effective.limit):
        yield result_cls.model_validate(row)


class SearchRepos:
    """Run ``GET /search/repositories`` with scope-aware defaults."""

    def __init__(
        self,
        search: GithubSearchService,
        teams: GithubTeamService,
        *,
        warn: WarnFn = _noop,
    ) -> None:
        self._search = search
        self._teams = teams
        self._warn = warn

    def __call__(
        self,
        filters: RepoSearchFilters,
        *,
        team_scopes: tuple[TeamScope, ...] = (),
    ) -> Iterator[RepoResult]:
        return _run_scoped_search(
            self._search.search_repositories,
            RepoResult,
            self._teams,
            filters,
            team_scopes=team_scopes,
            warn=self._warn,
        )


class SearchCode:
    """Run ``GET /search/code`` with scope-aware defaults."""

    def __init__(
        self,
        search: GithubSearchService,
        teams: GithubTeamService,
        *,
        warn: WarnFn = _noop,
    ) -> None:
        self._search = search
        self._teams = teams
        self._warn = warn

    def __call__(
        self,
        filters: CodeSearchFilters,
        *,
        team_scopes: tuple[TeamScope, ...] = (),
    ) -> Iterator[CodeResult]:
        return _run_scoped_search(
            self._search.search_code,
            CodeResult,
            self._teams,
            filters,
            team_scopes=team_scopes,
            warn=self._warn,
        )


class SearchIssues:
    """Run ``GET /search/issues`` with scope-aware defaults."""

    def __init__(
        self,
        search: GithubSearchService,
        teams: GithubTeamService,
        *,
        warn: WarnFn = _noop,
    ) -> None:
        self._search = search
        self._teams = teams
        self._warn = warn

    def __call__(
        self,
        filters: IssueSearchFilters,
        *,
        team_scopes: tuple[TeamScope, ...] = (),
    ) -> Iterator[IssueResult]:
        return _run_scoped_search(
            self._search.search_issues,
            IssueResult,
            self._teams,
            filters,
            team_scopes=team_scopes,
            warn=self._warn,
        )


class SearchUsers:
    """Run ``GET /search/users``.

    GitHub's user-search endpoint ignores ``user:`` / ``repo:`` /
    ``org:`` qualifiers, so this use case does not resolve teams or
    inject ``user:@me`` — the only search that returns global results
    by default.
    """

    def __init__(self, search: GithubSearchService) -> None:
        self._search = search

    def __call__(self, filters: UserSearchFilters) -> Iterator[UserResult]:
        q = filters.to_query_string()
        for row in self._search.search_users(q, sort=filters.sort, limit=filters.limit):
            yield UserResult.model_validate(row)
