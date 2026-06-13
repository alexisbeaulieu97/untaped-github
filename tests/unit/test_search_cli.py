"""End-to-end CLI tests for ``untaped github search`` (HTTP mocked via respx)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from untaped.settings import get_settings, register_profile_settings
from untaped.testing import CliInvoker

from untaped_github.cli import app
from untaped_github.settings import GithubSettings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    # Invoking the github app directly skips plugin registration, so mirror
    # the manifest's profile-settings contribution (idempotent for the same
    # model class) before each test.
    register_profile_settings("github", GithubSettings)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yml"
    cfg.write_text("github:\n  token: ghp_test\n")
    return cfg


def _write_list_view_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yml"
    cfg.write_text("ui:\n  collection_view: list\ngithub:\n  token: ghp_test\n")
    return cfg


def _write_missing_theme_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yml"
    cfg.write_text("ui:\n  theme: missing\ngithub:\n  token: ghp_test\n")
    return cfg


def test_search_repos_injects_at_me_and_renders_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    payload = {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "id": 1,
                "name": "alpha",
                "full_name": "octocat/alpha",
                "html_url": "https://github.com/octocat/alpha",
                "stargazers_count": 7,
            }
        ],
    }
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/repositories").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = CliInvoker().invoke(
            app,
            [
                "search",
                "repos",
                "--language",
                "python",
                "--format",
                "raw",
                "--columns",
                "full_name",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "octocat/alpha" in result.stdout
    sent_q = route.calls[0].request.url.params["q"]
    assert "user:@me" in sent_q
    assert "language:python" in sent_q


def test_search_repos_table_honors_list_collection_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_list_view_config(tmp_path)))

    payload = {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "id": 1,
                "name": "alpha",
                "full_name": "octocat/alpha",
                "html_url": "https://github.com/octocat/alpha",
                "stargazers_count": 7,
            }
        ],
    }
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/search/repositories").mock(return_value=httpx.Response(200, json=payload))
        result = CliInvoker().invoke(app, ["search", "repos", "--format", "table"])

    assert result.exit_code == 0, result.output
    assert "full_name: octocat/alpha" in result.stdout
    assert "name: alpha" in result.stdout
    assert "─" not in result.stdout
    assert "│" not in result.stdout


def test_search_repos_raw_ignores_invalid_ui_theme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_missing_theme_config(tmp_path)))

    payload = {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "id": 1,
                "name": "alpha",
                "full_name": "octocat/alpha",
                "html_url": "https://github.com/octocat/alpha",
                "stargazers_count": 7,
            }
        ],
    }
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/search/repositories").mock(return_value=httpx.Response(200, json=payload))
        result = CliInvoker().invoke(app, ["search", "repos", "--format", "raw"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "octocat/alpha"
    assert "\x1b[" not in result.output
    assert "unknown UI theme" not in result.output


def test_search_repos_rejects_command_local_profile_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Profile selection moved to the root `untaped --profile` option
    # (plugin API v4, accepted in any token position). The plugin's own
    # commands no longer define a local --profile, so it must be rejected
    # as an unknown option (usage error, exit 2).
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    result = CliInvoker().invoke(
        app,
        ["search", "repos", "--profile", "stage", "--format", "json"],
    )

    assert result.exit_code == 2, result.output
    assert "--profile" in result.output


def test_search_repos_with_explicit_org_does_not_inject_at_me(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/repositories").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        result = CliInvoker().invoke(app, ["search", "repos", "--org", "acme", "--format", "json"])

    assert result.exit_code == 0, result.output
    sent_q = route.calls[0].request.url.params["q"]
    assert "org:acme" in sent_q
    assert "user:@me" not in sent_q


def test_search_repos_team_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    team_repos = [
        {"full_name": "acme/api"},
        {"full_name": "acme/web"},
    ]
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/orgs/acme/teams/backend/repos").mock(
            return_value=httpx.Response(200, json=team_repos)
        )
        search_route = mock.get("/search/repositories").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        result = CliInvoker().invoke(
            app,
            ["search", "repos", "--team", "acme/backend", "--format", "json"],
        )

    assert result.exit_code == 0, result.output
    sent_q = search_route.calls[0].request.url.params["q"]
    assert sent_q == "(repo:acme/api OR repo:acme/web)"


def test_search_code_accepts_org_qualified_team_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    team_repos = [
        {"full_name": "acme/api"},
        {"full_name": "acme/web"},
    ]
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/orgs/acme/teams/backend/repos").mock(
            return_value=httpx.Response(200, json=team_repos)
        )
        route = mock.get("/search/code").mock(return_value=httpx.Response(200, json={"items": []}))
        result = CliInvoker().invoke(
            app,
            ["search", "code", "TODO", "--team", "acme/backend", "--format", "json"],
        )

    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["q"] == "TODO (repo:acme/api OR repo:acme/web)"


def test_search_issues_accepts_org_qualified_team_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    team_repos = [
        {"full_name": "acme/api"},
        {"full_name": "acme/web"},
    ]
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/orgs/acme/teams/backend/repos").mock(
            return_value=httpx.Response(200, json=team_repos)
        )
        route = mock.get("/search/issues").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        result = CliInvoker().invoke(
            app,
            [
                "search",
                "issues",
                "--team",
                "acme/backend",
                "--state",
                "open",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["q"] == "(repo:acme/api OR repo:acme/web) is:open"


def test_search_code_accepts_repeated_team_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/orgs/acme/teams/backend/repos").mock(
            return_value=httpx.Response(200, json=[{"full_name": "acme/api"}])
        )
        mock.get("/orgs/platform/teams/ops/repos").mock(
            return_value=httpx.Response(200, json=[{"full_name": "platform/deploy"}])
        )
        route = mock.get("/search/code").mock(return_value=httpx.Response(200, json={"items": []}))
        result = CliInvoker().invoke(
            app,
            [
                "search",
                "code",
                "TODO",
                "--team",
                "acme/backend",
                "--team",
                "platform/ops",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["q"] == "TODO (repo:acme/api OR repo:platform/deploy)"


def test_search_code_rejects_slug_team_with_single_org(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    result = CliInvoker().invoke(
        app,
        [
            "search",
            "code",
            "TODO",
            "--org",
            "acme",
            "--team",
            "backend",
            "--format",
            "json",
        ],
    )

    assert result.exit_code != 0
    assert "ORG/SLUG" in result.output


def test_search_code_passes_query_and_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    payload = {
        "items": [
            {
                "name": "main.py",
                "path": "src/main.py",
                "sha": "abc",
                "html_url": "https://x",
                "repository": {"full_name": "me/proj"},
            }
        ]
    }
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/code").mock(return_value=httpx.Response(200, json=payload))
        result = CliInvoker().invoke(
            app,
            ["search", "code", "TODO", "--language", "python", "--format", "json"],
        )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert parsed[0]["repo"] == "me/proj"
    sent_q = route.calls[0].request.url.params["q"]
    assert "TODO" in sent_q
    assert "language:python" in sent_q
    assert "user:@me" in sent_q


def test_search_code_repeated_repos_render_or_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/code").mock(return_value=httpx.Response(200, json={"items": []}))
        result = CliInvoker().invoke(
            app,
            [
                "search",
                "code",
                "TODO",
                "--repo",
                "acme/api",
                "--repo",
                "acme/web",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["q"] == "TODO (repo:acme/api OR repo:acme/web)"


def test_search_code_reads_repo_scopes_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/code").mock(return_value=httpx.Response(200, json={"items": []}))
        result = CliInvoker().invoke(
            app,
            ["search", "code", "TODO", "--repo-stdin", "--format", "json"],
            input="acme/api\nacme/web\n",
        )

    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["q"] == "TODO (repo:acme/api OR repo:acme/web)"


def test_search_code_combines_explicit_and_stdin_repo_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/code").mock(return_value=httpx.Response(200, json={"items": []}))
        result = CliInvoker().invoke(
            app,
            [
                "search",
                "code",
                "TODO",
                "--repo",
                "acme/api",
                "--repo-stdin",
                "--format",
                "json",
            ],
            input="acme/web\n",
        )

    assert result.exit_code == 0, result.output
    assert route.calls[0].request.url.params["q"] == "TODO (repo:acme/api OR repo:acme/web)"


def test_search_issues_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    payload = {
        "items": [
            {
                "id": 1,
                "number": 1,
                "title": "first",
                "state": "open",
                "html_url": "https://x",
                "repository_url": "https://api.github.com/repos/me/p",
                "user": {"login": "octocat"},
            }
        ]
    }
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/issues").mock(return_value=httpx.Response(200, json=payload))
        result = CliInvoker().invoke(
            app,
            [
                "search",
                "issues",
                "--state",
                "open",
                "--kind",
                "pr",
                "--label",
                "bug",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert parsed[0]["repo"] == "me/p"
    sent_q = route.calls[0].request.url.params["q"]
    for token in ("is:pr", "is:open", "label:bug", "user:@me"):
        assert token in sent_q


def test_search_issues_raw_repo_number_columns_are_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    payload = {
        "items": [
            {
                "id": 1,
                "number": 42,
                "title": "first",
                "state": "open",
                "html_url": "https://x",
                "repository_url": "https://api.github.com/repos/acme/api",
                "user": {"login": "octocat"},
            }
        ]
    }
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/search/issues").mock(return_value=httpx.Response(200, json=payload))
        result = CliInvoker().invoke(
            app,
            [
                "search",
                "issues",
                "--format",
                "raw",
                "--columns",
                "repo",
                "--columns",
                "number",
            ],
        )

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "acme/api\t42"


def test_search_users_no_at_me(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    payload = {
        "items": [
            {
                "id": 1,
                "login": "octocat",
                "type": "User",
                "html_url": "https://github.com/octocat",
            }
        ]
    }
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/users").mock(return_value=httpx.Response(200, json=payload))
        result = CliInvoker().invoke(
            app,
            ["search", "users", "--kind", "org", "--location", "montreal", "--format", "json"],
        )

    assert result.exit_code == 0, result.output
    sent_q = route.calls[0].request.url.params["q"]
    assert "user:@me" not in sent_q
    assert "type:org" in sent_q
    assert "location:montreal" in sent_q


def test_search_repos_follows_link_header_for_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    page1 = {
        "items": [
            {"id": 1, "name": "a", "full_name": "me/a", "html_url": "https://x"},
        ]
    }
    page2 = {
        "items": [
            {"id": 2, "name": "b", "full_name": "me/b", "html_url": "https://x"},
        ]
    }
    link = '<https://api.github.com/search/repositories?page=2>; rel="next"'

    with respx.mock(base_url="https://api.github.com") as mock:
        # First page returns Link: next; second page returns no Link.
        mock.get("/search/repositories", params={"page": "2"}).mock(
            return_value=httpx.Response(200, json=page2)
        )
        mock.get("/search/repositories").mock(
            return_value=httpx.Response(200, json=page1, headers={"Link": link})
        )
        result = CliInvoker().invoke(app, ["search", "repos", "--format", "json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert [r["full_name"] for r in parsed] == ["me/a", "me/b"]


def test_search_repos_respects_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    items = [
        {"id": i, "name": f"r{i}", "full_name": f"me/r{i}", "html_url": "https://x"}
        for i in range(5)
    ]
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/search/repositories").mock(
            return_value=httpx.Response(200, json={"items": items})
        )
        result = CliInvoker().invoke(app, ["search", "repos", "--limit", "2", "--format", "json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert len(parsed) == 2


def test_search_repos_default_limit_is_30(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Bare `search repos` (no --limit) used to paginate until GitHub's
    # 1000-result cap. The default is now 30 so a casual exploratory
    # query costs one of the user's 30/min search-rate-limit budget.
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    items = [
        {"id": i, "name": f"r{i}", "full_name": f"me/r{i}", "html_url": "https://x"}
        for i in range(50)
    ]
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/repositories").mock(
            return_value=httpx.Response(200, json={"items": items})
        )
        result = CliInvoker().invoke(app, ["search", "repos", "--format", "json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert len(parsed) == 30
    assert route.calls[0].request.url.params["per_page"] == "30"
    assert route.call_count == 1


def test_search_repos_limit_1000_paginates_fully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `--limit 1000` is the documented escape hatch for opting into
    # GitHub's hard maximum; the paginator must still walk the Link
    # header chain when the user asks for it explicitly.
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    page1 = {
        "items": [
            {"id": i, "name": f"r{i}", "full_name": f"me/r{i}", "html_url": "https://x"}
            for i in range(100)
        ]
    }
    page2 = {
        "items": [
            {"id": i, "name": f"r{i}", "full_name": f"me/r{i}", "html_url": "https://x"}
            for i in range(100, 200)
        ]
    }
    link = '<https://api.github.com/search/repositories?page=2>; rel="next"'
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/search/repositories", params={"page": "2"}).mock(
            return_value=httpx.Response(200, json=page2)
        )
        mock.get("/search/repositories").mock(
            return_value=httpx.Response(200, json=page1, headers={"Link": link})
        )
        result = CliInvoker().invoke(
            app, ["search", "repos", "--limit", "1000", "--format", "json"]
        )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert len(parsed) == 200


def test_search_repos_limit_above_1000_stops_at_github_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The CLI deliberately does NOT enforce a client-side max — passing
    # --limit 5000 is allowed and the paginator simply stops once
    # GitHub stops returning a `next` Link. Lock this stance so a
    # future contributor doesn't "tighten" the CLI with a max=1000
    # validator (which the issue body called out as out of scope).
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    items = [
        {"id": i, "name": f"r{i}", "full_name": f"me/r{i}", "html_url": "https://x"}
        for i in range(100)
    ]
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/search/repositories").mock(
            return_value=httpx.Response(200, json={"items": items})  # no Link header
        )
        result = CliInvoker().invoke(
            app, ["search", "repos", "--limit", "5000", "--format", "json"]
        )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert len(parsed) == 100  # GitHub stopped sending more; we honour it.


def test_search_repos_limit_zero_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A zero limit is a usage error, not a synonym for "all results".
    # Pin a non-zero usage error + the range message so a
    # future routing change (e.g. swallowing 0 → empty result, exit 0)
    # fails loudly instead of silently passing the looser exit≠0 check.
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    result = CliInvoker().invoke(app, ["search", "repos", "--limit", "0"])
    assert result.exit_code != 0, result.output
    assert "--limit" in result.output
    assert ">= 1" in result.output


def test_search_repos_help_advertises_default_30(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    result = CliInvoker().invoke(app, ["search", "repos", "--help"])
    assert result.exit_code == 0, result.output
    # Help output includes the default and documented cap.
    assert "30" in result.output
    assert "1000" in result.output  # cap mentioned in the help string


def test_search_code_default_limit_is_30(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # All four subcommands share SearchLimitOption — these tests pin
    # the contract per call site so a future refactor that hard-codes
    # a different default at one of the four would fail loudly.
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    items = [
        {
            "name": f"f{i}.py",
            "path": f"src/f{i}.py",
            "sha": f"sha{i}",
            "html_url": "https://x",
            "repository": {"full_name": "me/proj"},
        }
        for i in range(50)
    ]
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/code").mock(
            return_value=httpx.Response(200, json={"items": items})
        )
        result = CliInvoker().invoke(app, ["search", "code", "TODO", "--format", "json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert len(parsed) == 30
    assert route.calls[0].request.url.params["per_page"] == "30"


def test_search_users_default_limit_is_30(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    items = [
        {
            "id": i,
            "login": f"u{i}",
            "type": "User",
            "html_url": f"https://github.com/u{i}",
        }
        for i in range(50)
    ]
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/users").mock(
            return_value=httpx.Response(200, json={"items": items})
        )
        result = CliInvoker().invoke(app, ["search", "users", "octocat", "--format", "json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert len(parsed) == 30
    assert route.calls[0].request.url.params["per_page"] == "30"


def test_search_issues_default_limit_is_30(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Lock the contract on a second subcommand so the default isn't
    # accidentally regressed on only one of the four call sites.
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    items = [
        {
            "id": i,
            "number": i,
            "title": f"t{i}",
            "state": "open",
            "html_url": "https://x",
            "repository_url": "https://api.github.com/repos/me/p",
            "user": {"login": "octocat"},
        }
        for i in range(50)
    ]
    with respx.mock(base_url="https://api.github.com") as mock:
        route = mock.get("/search/issues").mock(
            return_value=httpx.Response(200, json={"items": items})
        )
        result = CliInvoker().invoke(app, ["search", "issues", "--format", "json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert len(parsed) == 30
    assert route.calls[0].request.url.params["per_page"] == "30"


def test_search_team_without_org_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    result = CliInvoker().invoke(app, ["search", "repos", "--team", "backend"])
    assert result.exit_code != 0
    assert "ORG/SLUG" in result.output


def test_search_team_with_extra_path_segment_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    result = CliInvoker().invoke(app, ["search", "repos", "--team", "acme/backend/extra"])
    assert result.exit_code != 0
    assert "ORG/SLUG" in result.output


def test_search_team_slug_with_multiple_orgs_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    result = CliInvoker().invoke(
        app,
        ["search", "repos", "--org", "a", "--org", "b", "--team", "backend"],
    )
    assert result.exit_code != 0
    assert "ORG/SLUG" in result.output
