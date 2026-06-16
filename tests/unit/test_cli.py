import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from untaped.settings import get_settings, register_profile_settings
from untaped.testing import CliInvoker

import untaped_github
import untaped_github.domain
from untaped_github.cli import app
from untaped_github.settings import GithubSettings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    # Invoking the github app directly skips the SDK profile-settings
    # registration, so mirror it (idempotent for the same model class)
    # before each test.
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


def test_root_package_public_surface_is_slim() -> None:
    assert untaped_github.__all__ == [
        "BatchRepoRefsResult",
        "GithubClient",
        "GithubSettings",
        "RepoRef",
        "RepoRefs",
        "app",
    ]
    assert "ScopedQueryBase" not in untaped_github.domain.__all__


def test_app_attribute_resolves_to_cli_app() -> None:
    assert untaped_github.app is app


def test_unknown_root_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="nonsense"):
        _ = untaped_github.nonsense


def test_whoami_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _write_config(tmp_path)
    monkeypatch.setenv("UNTAPED_CONFIG", str(cfg))

    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/user").mock(return_value=httpx.Response(200, json={"login": "octocat", "id": 1}))
        result = CliInvoker().invoke(app, ["whoami", "--format", "raw", "--columns", "login"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "octocat"


def test_whoami_pipe_tags_github_user_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/user").mock(return_value=httpx.Response(200, json={"login": "octocat", "id": 1}))
        result = CliInvoker().invoke(app, ["whoami", "--format", "pipe"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout.splitlines()[0])
    assert envelope["kind"] == "github.user"
    assert envelope["record"]["login"] == "octocat"


def test_whoami_table_honors_list_collection_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _write_list_view_config(tmp_path)
    monkeypatch.setenv("UNTAPED_CONFIG", str(cfg))

    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/user").mock(return_value=httpx.Response(200, json={"login": "octocat", "id": 1}))
        result = CliInvoker().invoke(app, ["whoami", "--format", "table"])

    assert result.exit_code == 0, result.output
    assert "login: octocat" in result.stdout
    assert "id: 1" in result.stdout
    assert "─" not in result.stdout
    assert "│" not in result.stdout


def test_whoami_raw_ignores_invalid_ui_theme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _write_missing_theme_config(tmp_path)
    monkeypatch.setenv("UNTAPED_CONFIG", str(cfg))

    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/user").mock(return_value=httpx.Response(200, json={"login": "octocat", "id": 1}))
        result = CliInvoker().invoke(app, ["whoami", "--format", "raw"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "octocat"
    assert "\x1b[" not in result.output
    assert "unknown UI theme" not in result.output


def test_whoami_rejects_command_local_profile_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Profile selection moved to the root `untaped --profile` option
    # (plugin API v4, accepted in any token position). The tool's own
    # commands no longer define a local --profile, so it must be rejected
    # as an unknown option (usage error, exit 2).
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    result = CliInvoker().invoke(
        app, ["whoami", "--profile", "stage", "--format", "raw", "--columns", "login"]
    )

    assert result.exit_code == 2, result.output
    assert "--profile" in result.output


def test_whoami_requires_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(tmp_path / "missing.yml"))
    result = CliInvoker().invoke(app, ["whoami"])
    assert result.exit_code != 0
    assert "token" in str(result.exception) or "token" in result.output


def test_whoami_rejects_blank_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yml"
    cfg.write_text('github:\n  token: "   "\n')
    monkeypatch.setenv("UNTAPED_CONFIG", str(cfg))
    result = CliInvoker().invoke(app, ["whoami"])
    assert result.exit_code != 0
    assert "token" in str(result.exception) or "token" in result.output
