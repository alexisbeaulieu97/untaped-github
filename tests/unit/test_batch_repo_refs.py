"""Unit tests for ``GithubClient.batch_repo_refs`` (GraphQL batched ref probe)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr
from untaped.api import HttpError, UntapedError

from untaped_github import GithubClient, GithubSettings


def _client(base_url: str = "https://api.github.com") -> GithubClient:
    return GithubClient(GithubSettings(token=SecretStr("ghp_test"), base_url=base_url))


def _ref_node(name: str, target: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "target": target}


def _connection(
    nodes: list[dict[str, Any]],
    *,
    has_next: bool = False,
    end_cursor: str | None = None,
) -> dict[str, Any]:
    return {"pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor}, "nodes": nodes}


def _repo_node(
    full_name: str,
    *,
    default_branch: str | None = "main",
    heads: dict[str, Any] | None = None,
    tags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "nameWithOwner": full_name,
        "defaultBranchRef": {"name": default_branch} if default_branch else None,
    }
    if heads is not None:
        node["heads"] = heads
    if tags is not None:
        node["tags"] = tags
    return node


def _payload(
    repos: dict[str, Any],
    *,
    errors: list[dict[str, Any]] | None = None,
    remaining: int = 4999,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "data": {
            **repos,
            "rateLimit": {"cost": 1, "remaining": remaining, "resetAt": "2026-06-10T00:00:00Z"},
        }
    }
    if errors is not None:
        body["errors"] = errors
    return body


def _query(route: respx.Route, call: int = 0) -> str:
    body = json.loads(route.calls[call].request.content)
    query = body["query"]
    assert isinstance(query, str)
    return query


def test_batch_repo_refs_returns_refs_default_branch_and_rate_limit() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.post("/graphql").mock(
            return_value=httpx.Response(
                200,
                json=_payload(
                    {
                        "r0": _repo_node(
                            "acme/site",
                            heads=_connection([_ref_node("main", {"oid": "c1"})]),
                            tags=_connection(
                                [
                                    # Lightweight tag: target is the commit itself.
                                    _ref_node("v0.9.0", {"oid": "c8"}),
                                    # Annotated tag: peel one level to the commit.
                                    _ref_node("v1.0.0", {"oid": "t1", "target": {"oid": "c9"}}),
                                    # Tag-of-tag: peel two levels to the commit.
                                    _ref_node(
                                        "v1.0.1",
                                        {
                                            "oid": "t2",
                                            "target": {"oid": "t3", "target": {"oid": "c10"}},
                                        },
                                    ),
                                ]
                            ),
                        ),
                        "r1": _repo_node(
                            "acme/empty",
                            default_branch=None,
                            heads=_connection([]),
                            tags=_connection([]),
                        ),
                    },
                    remaining=4998,
                ),
            )
        )
        with _client() as client:
            result = client.batch_repo_refs(["acme/site", "acme/empty"])

    assert route.call_count == 1
    site, empty = result.repos
    assert site.full_name == "acme/site"
    assert site.default_branch == "main"
    assert [(ref.kind, ref.name, ref.sha) for ref in site.refs] == [
        ("heads", "main", "c1"),
        ("tags", "v0.9.0", "c8"),
        ("tags", "v1.0.0", "c9"),
        ("tags", "v1.0.1", "c10"),
    ]
    assert empty.full_name == "acme/empty"
    assert empty.default_branch is None
    assert empty.refs == ()
    assert result.missing == ()
    assert result.rate_limit_remaining == 4998
    query = _query(route)
    assert 'r0: repository(owner: "acme", name: "site")' in query
    assert 'r1: repository(owner: "acme", name: "empty")' in query
    assert "rateLimit { cost remaining resetAt }" in query


def test_batch_repo_refs_chunks_requests_by_chunk_size() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.post("/graphql").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=_payload(
                        {
                            "r0": _repo_node("acme/a", heads=_connection([]), tags=_connection([])),
                            "r1": _repo_node("acme/b", heads=_connection([]), tags=_connection([])),
                        }
                    ),
                ),
                httpx.Response(
                    200,
                    json=_payload(
                        {"r0": _repo_node("acme/c", heads=_connection([]), tags=_connection([]))},
                        remaining=4997,
                    ),
                ),
            ]
        )
        with _client() as client:
            result = client.batch_repo_refs(["acme/a", "acme/b", "acme/c"], chunk_size=2)

    assert route.call_count == 2
    first = _query(route, 0)
    assert 'name: "a"' in first
    assert 'name: "b"' in first
    assert 'name: "c"' not in first
    second = _query(route, 1)
    assert 'r0: repository(owner: "acme", name: "c")' in second
    assert [repo.full_name for repo in result.repos] == ["acme/a", "acme/b", "acme/c"]
    assert result.rate_limit_remaining == 4997


def test_batch_repo_refs_follows_ref_pagination_cursor() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.post("/graphql").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=_payload(
                        {
                            "r0": _repo_node(
                                "acme/site",
                                heads=_connection(
                                    [_ref_node("main", {"oid": "c1"})],
                                    has_next=True,
                                    end_cursor="CUR",
                                ),
                            )
                        },
                        remaining=4990,
                    ),
                ),
                httpx.Response(
                    200,
                    json=_payload(
                        {"r0": {"heads": _connection([_ref_node("dev", {"oid": "c2"})])}},
                        remaining=4989,
                    ),
                ),
            ]
        )
        with _client() as client:
            result = client.batch_repo_refs(["acme/site"], kinds=("heads",))

    assert route.call_count == 2
    assert 'after: "CUR"' in _query(route, 1)
    (site,) = result.repos
    assert [(ref.name, ref.sha) for ref in site.refs] == [("main", "c1"), ("dev", "c2")]
    assert result.rate_limit_remaining == 4989


def test_batch_repo_refs_collects_not_found_repos_into_missing() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.post("/graphql").mock(
            return_value=httpx.Response(
                200,
                json=_payload(
                    {
                        "r0": _repo_node("acme/site", heads=_connection([]), tags=_connection([])),
                        "r1": None,
                    },
                    errors=[
                        {
                            "type": "NOT_FOUND",
                            "path": ["r1"],
                            "message": "Could not resolve to a Repository",
                        }
                    ],
                ),
            )
        )
        with _client() as client:
            result = client.batch_repo_refs(["acme/site", "acme/gone"])

    assert [repo.full_name for repo in result.repos] == ["acme/site"]
    assert result.missing == ("acme/gone",)


def test_batch_repo_refs_skips_refs_with_null_target() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.post("/graphql").mock(
            return_value=httpx.Response(
                200,
                json=_payload(
                    {
                        "r0": _repo_node(
                            "acme/site",
                            heads=_connection(
                                [
                                    _ref_node("main", {"oid": "c1"}),
                                    # GitHub's schema allows Ref.target to be
                                    # null; such a ref has no resolvable object.
                                    {"name": "broken", "target": None},
                                    _ref_node("dev", {"oid": "c2"}),
                                ]
                            ),
                        )
                    }
                ),
            )
        )
        with _client() as client:
            result = client.batch_repo_refs(["acme/site"], kinds=("heads",))

    (site,) = result.repos
    assert [(ref.name, ref.sha) for ref in site.refs] == [("main", "c1"), ("dev", "c2")]


def test_batch_repo_refs_dedupes_repeated_kinds() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.post("/graphql").mock(
            return_value=httpx.Response(
                200,
                json=_payload(
                    {
                        "r0": _repo_node(
                            "acme/site",
                            heads=_connection([_ref_node("main", {"oid": "c1"})]),
                        )
                    }
                ),
            )
        )
        with _client() as client:
            result = client.batch_repo_refs(["acme/site"], kinds=("heads", "heads"))

    # The duplicate kind is dropped: one connection in the query, and the
    # refs are not collected twice.
    assert _query(route).count("refs/heads/") == 1
    (site,) = result.repos
    assert [(ref.name, ref.sha) for ref in site.refs] == [("main", "c1")]


def test_batch_repo_refs_collects_forbidden_repos_into_missing() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.post("/graphql").mock(
            return_value=httpx.Response(
                200,
                json=_payload(
                    {
                        "r0": _repo_node("acme/site", heads=_connection([]), tags=_connection([])),
                        "r1": None,
                    },
                    errors=[
                        {
                            "type": "FORBIDDEN",
                            "path": ["r1"],
                            "message": "Resource not accessible",
                        }
                    ],
                ),
            )
        )
        with _client() as client:
            result = client.batch_repo_refs(["acme/site", "acme/private"])

    assert [repo.full_name for repo in result.repos] == ["acme/site"]
    assert result.missing == ("acme/private",)


def test_batch_repo_refs_raises_when_repo_lost_during_ref_pagination() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.post("/graphql").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=_payload(
                        {
                            "r0": _repo_node(
                                "acme/site",
                                heads=_connection(
                                    [_ref_node("main", {"oid": "c1"})],
                                    has_next=True,
                                    end_cursor="CUR",
                                ),
                            )
                        }
                    ),
                ),
                # The repo resolved in the batch query but vanishes
                # (deleted mid-probe) before the pagination follow-up.
                httpx.Response(
                    200,
                    json=_payload(
                        {"r0": None},
                        errors=[
                            {
                                "type": "NOT_FOUND",
                                "path": ["r0"],
                                "message": "Could not resolve to a Repository",
                            }
                        ],
                    ),
                ),
            ]
        )
        with (
            _client() as client,
            pytest.raises(UntapedError, match="lost access to acme/site during ref pagination"),
        ):
            client.batch_repo_refs(["acme/site"], kinds=("heads",))


def test_batch_repo_refs_raises_on_other_graphql_errors() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.post("/graphql").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": None,
                    "errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}],
                },
            )
        )
        with (
            _client() as client,
            pytest.raises(UntapedError, match="API rate limit exceeded"),
        ):
            client.batch_repo_refs(["acme/site"])


def test_batch_repo_refs_raises_on_null_repo_without_error() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.post("/graphql").mock(return_value=httpx.Response(200, json=_payload({"r0": None})))
        with _client() as client, pytest.raises(UntapedError, match="acme/site"):
            client.batch_repo_refs(["acme/site"])


def test_batch_repo_refs_derives_ghe_graphql_endpoint() -> None:
    with respx.mock(base_url="https://ghe.example.com") as mock:
        route = mock.post("/api/graphql").mock(
            return_value=httpx.Response(
                200,
                json=_payload(
                    {"r0": _repo_node("acme/site", heads=_connection([]), tags=_connection([]))}
                ),
            )
        )
        with _client(base_url="https://ghe.example.com/api/v3") as client:
            result = client.batch_repo_refs(["acme/site"])

    assert route.call_count == 1
    assert result.repos[0].full_name == "acme/site"


def test_batch_repo_refs_heads_only_omits_tags_from_query() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.post("/graphql").mock(
            return_value=httpx.Response(
                200,
                json=_payload({"r0": _repo_node("acme/site", heads=_connection([]))}),
            )
        )
        with _client() as client:
            result = client.batch_repo_refs(["acme/site"], kinds=("heads",))

    query = _query(route)
    assert "refs/heads/" in query
    assert "refs/tags/" not in query
    assert result.repos[0].refs == ()


def test_batch_repo_refs_retries_5xx_with_chunk_split_in_half() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.post("/graphql").mock(
            side_effect=[
                httpx.Response(502, text="Bad Gateway"),
                httpx.Response(
                    200,
                    json=_payload(
                        {"r0": _repo_node("acme/a", heads=_connection([]), tags=_connection([]))}
                    ),
                ),
                httpx.Response(
                    200,
                    json=_payload(
                        {"r0": _repo_node("acme/b", heads=_connection([]), tags=_connection([]))}
                    ),
                ),
            ]
        )
        with _client() as client:
            result = client.batch_repo_refs(["acme/a", "acme/b"])

    assert route.call_count == 3
    assert 'name: "a"' in _query(route, 1)
    assert 'name: "b"' not in _query(route, 1)
    assert 'name: "b"' in _query(route, 2)
    assert [repo.full_name for repo in result.repos] == ["acme/a", "acme/b"]


def test_batch_repo_refs_raises_when_split_half_still_5xxs() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.post("/graphql").mock(
            side_effect=[
                httpx.Response(502, text="Bad Gateway"),
                httpx.Response(502, text="Bad Gateway"),
            ]
        )
        with _client() as client, pytest.raises(HttpError):
            client.batch_repo_refs(["acme/a", "acme/b"])

    assert route.call_count == 2


def test_batch_repo_refs_does_not_split_single_repo_chunk_on_5xx() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.post("/graphql").mock(side_effect=[httpx.Response(502, text="Bad Gateway")])
        with _client() as client, pytest.raises(HttpError):
            client.batch_repo_refs(["acme/a"])

    assert route.call_count == 1


def test_batch_repo_refs_does_not_retry_4xx() -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.post("/graphql").mock(side_effect=[httpx.Response(401, text="Unauthorized")])
        with _client() as client, pytest.raises(HttpError):
            client.batch_repo_refs(["acme/a", "acme/b"])

    assert route.call_count == 1


@pytest.mark.parametrize("bad", ["site", "acme/", "/site", "acme/site/extra", ""])
def test_batch_repo_refs_rejects_invalid_repo_strings(bad: str) -> None:
    # UntapedError, not ValueError: repo strings can come from user
    # source config, and core ``report_errors`` renders UntapedError
    # cleanly instead of as a traceback.
    with _client() as client, pytest.raises(UntapedError, match="owner/name"):
        client.batch_repo_refs([bad])


def test_batch_repo_refs_rejects_unknown_kind() -> None:
    with _client() as client, pytest.raises(ValueError, match="releases"):
        client.batch_repo_refs(["acme/site"], kinds=("heads", "releases"))


def test_batch_repo_refs_rejects_empty_kinds() -> None:
    with _client() as client, pytest.raises(ValueError, match="kinds"):
        client.batch_repo_refs(["acme/site"], kinds=())


def test_batch_repo_refs_rejects_non_positive_chunk_size() -> None:
    with _client() as client, pytest.raises(ValueError, match="chunk_size"):
        client.batch_repo_refs(["acme/site"], chunk_size=0)


def test_batch_repo_refs_with_no_repos_makes_no_requests() -> None:
    with respx.mock(base_url="https://api.github.com"), _client() as client:
        result = client.batch_repo_refs([])

    assert result.repos == ()
    assert result.missing == ()
    assert result.rate_limit_remaining is None
