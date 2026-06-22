"""Unit tests for repository inventory use cases."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

from untaped_github.application import GithubRepoListService, ListRepos, RepoListFilters, TeamScope


class _StubRepoLists:
    def __init__(
        self,
        *,
        orgs: dict[str, list[dict[str, Any]]] | None = None,
        teams: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._orgs = orgs or {}
        self._teams = teams or {}
        self.calls: list[tuple[str, str, str | None]] = []

    def list_org_repos(self, org: str) -> Iterator[dict[str, Any]]:
        self.calls.append(("org", org, None))
        return iter(self._orgs.get(org, []))

    def list_team_repos(self, org: str, team_slug: str) -> Iterator[dict[str, Any]]:
        self.calls.append(("team", org, team_slug))
        return iter(self._teams.get((org, team_slug), []))


def _service(stub: _StubRepoLists) -> GithubRepoListService:
    return cast(GithubRepoListService, stub)


def _repo(
    full_name: str,
    *,
    archived: bool = False,
    fork: bool = False,
    name: str | None = None,
    ssh_url: str | None = None,
) -> dict[str, Any]:
    leaf = name or full_name.rsplit("/", 1)[1]
    return {
        "full_name": full_name,
        "name": leaf,
        "html_url": f"https://github.com/{full_name}",
        "clone_url": f"https://github.com/{full_name}.git",
        "ssh_url": ssh_url or f"git@github.com:{full_name}.git",
        "default_branch": "main",
        "private": True,
        "archived": archived,
        "fork": fork,
    }


def test_list_repos_dedupes_filters_and_sorts_complete_inventory() -> None:
    stub = _StubRepoLists(
        orgs={
            "acme": [
                _repo("acme/zeta"),
                _repo("acme/play-api"),
                _repo("acme/play-old", archived=True),
                _repo("acme/play-fork", fork=True),
            ]
        },
        teams={
            ("platform", "ops"): [
                _repo("platform/play-role"),
                _repo("acme/play-api"),
            ],
        },
    )
    use_case = ListRepos(_service(stub))

    rows = list(
        use_case(
            RepoListFilters(pattern="play*", archived=False, fork=False),
            orgs=("acme",),
            team_scopes=(TeamScope("platform", "ops"),),
        )
    )

    assert stub.calls == [("org", "acme", None), ("team", "platform", "ops")]
    assert [row.full_name for row in rows] == ["acme/play-api", "platform/play-role"]


def test_list_repos_pattern_without_slash_matches_leaf_name_case_insensitively() -> None:
    stub = _StubRepoLists(orgs={"acme": [_repo("acme/Play-Api"), _repo("acme/api-play")]})
    use_case = ListRepos(_service(stub))

    rows = list(use_case(RepoListFilters(pattern="play*"), orgs=("acme",)))

    assert [row.full_name for row in rows] == ["acme/Play-Api"]


def test_list_repos_pattern_with_slash_matches_full_name() -> None:
    stub = _StubRepoLists(orgs={"acme": [_repo("acme/play-api"), _repo("other/play-api")]})
    use_case = ListRepos(_service(stub))

    rows = list(use_case(RepoListFilters(pattern="acme/play*"), orgs=("acme",)))

    assert [row.full_name for row in rows] == ["acme/play-api"]


def test_list_repos_regex_matches_selected_target_case_insensitively() -> None:
    stub = _StubRepoLists(orgs={"acme": [_repo("acme/Play-1"), _repo("acme/play-x")]})
    use_case = ListRepos(_service(stub))

    rows = list(use_case(RepoListFilters(pattern=r"^acme/play-\d+$", regex=True), orgs=("acme",)))

    assert [row.full_name for row in rows] == ["acme/Play-1"]
