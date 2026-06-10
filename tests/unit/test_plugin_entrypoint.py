"""Entry point and root-app integration checks for the GitHub plugin."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterator
from importlib.metadata import entry_points
from pathlib import Path

import httpx
import pytest
import respx
from untaped import get_settings
from untaped.main import build_app
from untaped.plugins import PluginRegistry
from untaped.settings import reset_config_registry_for_tests
from untaped.testing import CliInvoker

from untaped_github.plugin import plugin as github_plugin

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    cfg = tmp_path / "config.yml"
    monkeypatch.setenv("UNTAPED_CONFIG", str(cfg))
    monkeypatch.delenv("UNTAPED_PROFILE", raising=False)
    reset_config_registry_for_tests()
    get_settings.cache_clear()
    yield cfg
    os.environ.pop("UNTAPED_PROFILE", None)
    reset_config_registry_for_tests()
    get_settings.cache_clear()


def test_github_plugin_entry_point_is_declared() -> None:
    matches = [
        ep
        for ep in entry_points(group="untaped.plugins")
        if ep.name == "github" and ep.value == "untaped_github.plugin:plugin"
    ]

    assert matches


def test_github_plugin_declares_untaped_api_version() -> None:
    assert github_plugin.untaped_api_version == 2


def test_untaped_source_tracks_core_migration_branch_for_pr_stack() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    source = data["tool"]["uv"]["sources"]["untaped"]

    assert source == {
        "git": "https://github.com/alexisbeaulieu97/untaped",
        "branch": "cyclopts-migration",
    }


def test_root_app_can_register_github_plugin() -> None:
    app = build_app(plugins=[github_plugin])

    result = CliInvoker().invoke(app, ["github", "--help"])

    assert result.exit_code == 0, result.output
    assert "Inspect and search GitHub" in result.output


def test_github_plugin_registers_agent_skill() -> None:
    registry = PluginRegistry()

    github_plugin.register(registry)

    spec = registry.skills["untaped-github"]
    assert spec.description == "Use the untaped GitHub plugin."
    assert spec.source.joinpath("SKILL.md").is_file()


def test_config_list_includes_registered_github_settings() -> None:
    app = build_app(plugins=[github_plugin])

    result = CliInvoker().invoke(app, ["config", "list", "--format", "raw", "--columns", "key"])

    assert result.exit_code == 0, result.output
    assert "github.base_url" in result.stdout
    assert "github.token" in result.stdout


def test_config_list_redacts_github_token(_isolate_config: Path) -> None:
    _isolate_config.write_text("profiles:\n  default:\n    github:\n      token: ghp_secret\n")
    app = build_app(plugins=[github_plugin])

    result = CliInvoker().invoke(
        app, ["config", "list", "--format", "raw", "--columns", "key", "--columns", "value"]
    )

    assert result.exit_code == 0, result.output
    assert "ghp_secret" not in result.stdout
    assert "github.token\t***" in result.stdout


def test_root_app_uses_registered_github_settings(_isolate_config: Path) -> None:
    _isolate_config.write_text("profiles:\n  default:\n    github:\n      token: ghp_test\n")
    app = build_app(plugins=[github_plugin])

    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/user").mock(return_value=httpx.Response(200, json={"login": "octocat", "id": 1}))
        result = CliInvoker().invoke(
            app, ["github", "whoami", "--format", "raw", "--columns", "login"]
        )

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "octocat"
