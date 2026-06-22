"""Unit tests for pure repository inventory filter helpers."""

from __future__ import annotations

import pytest

from untaped_github.domain.models import RepoListResult
from untaped_github.domain.repo_filters import repo_pattern_matches


def _repo(full_name: str) -> RepoListResult:
    return RepoListResult(
        full_name=full_name,
        name=full_name.rsplit("/", 1)[1],
        html_url=f"https://github.com/{full_name}",
    )


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("api-service", ["acme/api-service", "beta/api-service"]),
        ("acme/*", ["acme/api-service", "acme/worker"]),
        ("*/api-service", ["acme/api-service", "beta/api-service"]),
        ("API-*", ["acme/api-service", "beta/api-service"]),
    ],
)
def test_glob_pattern_targeting_is_slash_aware_and_case_insensitive(
    pattern: str, expected: list[str]
) -> None:
    repos = [
        _repo("acme/api-service"),
        _repo("beta/api-service"),
        _repo("acme/worker"),
        _repo("beta/worker"),
    ]

    matched = [repo.full_name for repo in repos if repo_pattern_matches(repo, pattern)]

    assert matched == expected


def test_regex_pattern_targeting_is_slash_aware_and_case_insensitive() -> None:
    repos = [_repo("acme/API-service"), _repo("beta/api-service"), _repo("acme/worker")]

    matched = [
        repo.full_name
        for repo in repos
        if repo_pattern_matches(repo, r"^acme/api-service$", regex=True)
    ]

    assert matched == ["acme/API-service"]
