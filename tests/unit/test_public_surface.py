"""Public package API contract tests."""

from __future__ import annotations

import untaped_github


def test_public_all_is_curated_ansible_contract() -> None:
    assert untaped_github.__all__ == [
        "BatchRepoRefsFailure",
        "BatchRepoRefsResult",
        "GithubClient",
        "GithubGraphqlError",
        "GithubSettings",
        "RepoRef",
        "RepoRefs",
        "RepositoryInventoryItem",
        "RepositoryInventoryScope",
        "ResolveRepositoryInventory",
        "TeamScope",
        "app",
        "normalize_team_scopes",
    ]
