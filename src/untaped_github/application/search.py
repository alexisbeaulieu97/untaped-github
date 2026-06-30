"""Use cases: search GitHub for repos, code, issues, and users."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from itertools import islice
from typing import Any

from pydantic import BaseModel
from untaped.api import HttpStatusError, UntapedError

from untaped_github.application.ports import GithubSearchService, GithubTeamService
from untaped_github.application.scopes import TeamScope
from untaped_github.domain import (
    CodeResult,
    CodeSearchFilters,
    IssueResult,
    IssueSearchFilters,
    RepoResult,
    RepoSearchFilters,
    UserResult,
    UserSearchFilters,
)
from untaped_github.domain.queries import ScopedQueryBase

WarnFn = Callable[[str], None]

# Code and issue search still keep generated team OR groups small. Repository
# search resolves full teams and splits requests by the decoded q-length budget.
MAX_TEAM_REPO_QUALIFIERS = 6
MAX_SEARCH_QUERY_Q_LENGTH = 256
_REPOSITORY_SEARCH_ENDPOINT = "/search/repositories"


def _noop(_: str) -> None:
    pass


def _resolve_team_repos(
    teams: GithubTeamService,
    *,
    team_scopes: tuple[TeamScope, ...],
    warn: WarnFn,
    max_repos_per_team: int | None = MAX_TEAM_REPO_QUALIFIERS,
) -> tuple[str, ...]:
    """Pre-resolve team scopes into ``owner/name`` repo strings.

    When ``max_repos_per_team`` is set, bound expansion at ``N + 1`` so a
    5k-repo team doesn't drag every page over the wire just to be truncated.
    """
    all_repos: list[str] = []
    for scope in team_scopes:
        repos: list[str] = []
        entries = teams.list_team_repos(scope.org, scope.slug)
        if max_repos_per_team is not None:
            entries = islice(entries, max_repos_per_team + 1)
        for entry in entries:
            full_name = entry.get("full_name")
            if isinstance(full_name, str) and full_name:
                repos.append(full_name)
        if max_repos_per_team is not None and len(repos) > max_repos_per_team:
            warn(
                f"team {scope.org}/{scope.slug} has more than {max_repos_per_team} repos; "
                "truncating to stay under GitHub's query length limit"
            )
            repos = repos[:max_repos_per_team]
        all_repos.extend(repos)
    return tuple(all_repos)


def _apply_scope_defaults[F: ScopedQueryBase](filters: F, team_repos: tuple[str, ...]) -> F:
    """Merge team-resolved repos and inject ``user:@me`` when no scope set."""
    repos = _dedupe_repos((*filters.repos, *team_repos))
    has_scope = bool(filters.user or filters.orgs or repos)
    overrides: dict[str, object] = {"repos": repos}
    if not has_scope:
        overrides["user"] = "@me"
    return filters.model_copy(update=overrides)


def _dedupe_repos(repos: tuple[str, ...]) -> tuple[str, ...]:
    """Deduplicate repository scopes while preserving first-seen order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for repo in repos:
        if repo in seen:
            continue
        seen.add(repo)
        deduped.append(repo)
    return tuple(deduped)


def _repo_search_batches(filters: RepoSearchFilters) -> tuple[RepoSearchFilters, ...]:
    """Split repository search filters into decoded-q-length-safe batches."""
    repos = _dedupe_repos(filters.repos)
    if not repos:
        _ensure_search_query_fits(filters.to_query_string())
        return (filters,)

    batches: list[RepoSearchFilters] = []
    current: list[str] = []
    for repo in repos:
        candidate = (*current, repo)
        candidate_filters = filters.model_copy(update={"repos": candidate})
        candidate_q = candidate_filters.to_query_string()
        if len(candidate_q) <= MAX_SEARCH_QUERY_Q_LENGTH:
            current.append(repo)
            continue
        if not current:
            _raise_oversized_search_query(candidate_q)
        batches.append(filters.model_copy(update={"repos": tuple(current)}))
        current = [repo]
        first_query = filters.model_copy(update={"repos": tuple(current)}).to_query_string()
        _ensure_search_query_fits(first_query)
    if current:
        batches.append(filters.model_copy(update={"repos": tuple(current)}))
    return tuple(batches)


def _ensure_search_query_fits(q: str) -> None:
    if len(q) > MAX_SEARCH_QUERY_Q_LENGTH:
        _raise_oversized_search_query(q)


def _raise_oversized_search_query(q: str) -> None:
    raise UntapedError(
        "GitHub repository search query length "
        f"{len(q)} exceeds {MAX_SEARCH_QUERY_Q_LENGTH}; narrow the free-text query, "
        "use shorter explicit repo scopes, or search a narrower repository set."
    )


def _github_search_validation_error(exc: HttpStatusError, q: str) -> UntapedError:
    detail = _github_error_detail(exc.body)
    suffix = f": {detail}" if detail else ""
    return UntapedError(
        "GitHub repository search validation failed for "
        f"{_REPOSITORY_SEARCH_ENDPOINT} (query length {len(q)}): {exc}{suffix}"
    )


def _github_error_detail(body: str | None) -> str | None:
    if not body:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip() or None
    if not isinstance(data, dict):
        return body.strip() or None
    details: list[str] = []
    for key in ("message", "error", "detail"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            details.append(value.strip())
    errors = data.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict):
                value = item.get("message")
                if isinstance(value, str) and value.strip():
                    details.append(value.strip())
    deduped: list[str] = []
    for detail in details:
        if detail not in deduped:
            deduped.append(detail)
    return "; ".join(deduped) if deduped else body.strip() or None


_SearchMethod = Callable[..., Iterator[dict[str, Any]]]


def _run_scoped_search[F: RepoSearchFilters | IssueSearchFilters, R: BaseModel](
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
        team_repos = _resolve_team_repos(
            self._teams,
            team_scopes=team_scopes,
            warn=self._warn,
            max_repos_per_team=None,
        )
        effective = _apply_scope_defaults(filters, team_repos)
        rows: list[RepoResult] = []
        seen: set[str] = set()
        for batch in _repo_search_batches(effective):
            q = batch.to_query_string()
            try:
                search_rows = self._search.search_repositories(
                    q,
                    sort=batch.sort,
                    limit=batch.limit,
                )
                for row in search_rows:
                    result = RepoResult.model_validate(row)
                    if result.full_name in seen:
                        continue
                    seen.add(result.full_name)
                    rows.append(result)
            except HttpStatusError as exc:
                if exc.status_code == 422:
                    raise _github_search_validation_error(exc, q) from exc
                raise
        if effective.limit is not None:
            rows = rows[: effective.limit]
        return iter(rows)


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
        team_repos = _resolve_team_repos(self._teams, team_scopes=team_scopes, warn=self._warn)
        effective = _apply_scope_defaults(filters, team_repos)
        q = effective.to_query_string()
        for row in self._search.search_code(q, limit=effective.limit):
            yield CodeResult.model_validate(row)


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
