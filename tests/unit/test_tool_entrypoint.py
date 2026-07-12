"""Entry-point and SDK-wiring checks for the untaped-github CLI.

untaped-github is now a standalone tool: it ships a console script that runs
``run_tool(app, SPEC)`` instead of an ``untaped.plugins`` entry point. These
tests drive the wired app's meta exactly as the installed CLI would.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator
from importlib.metadata import entry_points
from pathlib import Path

import httpx
import pytest
import respx
from untaped.api import build_tool_app
from untaped.identity import reset_tool_command
from untaped.settings import get_settings, reset_config_registry_for_tests
from untaped.testing import CliInvoker

from untaped_github.__main__ import SPEC, main
from untaped_github.cli import app as _build_reference_app  # noqa: F401 - import smoke

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    cfg = tmp_path / "config.yml"
    monkeypatch.setenv("UNTAPED_CONFIG", str(cfg))
    monkeypatch.delenv("UNTAPED_PROFILE", raising=False)
    reset_config_registry_for_tests()
    reset_tool_command()
    get_settings.cache_clear()
    yield cfg
    reset_config_registry_for_tests()
    reset_tool_command()
    get_settings.cache_clear()


def _wired():
    from untaped_github.cli import app

    return build_tool_app(app, SPEC)


def test_console_script_is_declared() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert data["project"]["scripts"]["untaped-github"] == "untaped_github.__main__:main"


def test_no_untaped_plugins_entry_point() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert "untaped.plugins" not in data["project"].get("entry-points", {})
    assert not [ep for ep in entry_points(group="untaped.plugins") if ep.name == "github"]


def test_spec_is_well_formed() -> None:
    assert SPEC.command == "untaped-github"
    assert SPEC.section == "github"
    assert callable(main)
    (skill,) = SPEC.skills
    assert skill.name == "untaped-github"
    assert skill.source.joinpath("SKILL.md").is_file()


def test_groups_are_mounted_and_whoami_runs(_isolate: Path) -> None:
    # Under run_tool the profiles layout is always active, so config is
    # profile-scoped (the `default` profile is the base layer).
    _isolate.write_text(
        "profiles:\n  default:\n    github:\n      token: ghp_test\n", encoding="utf-8"
    )
    get_settings.cache_clear()
    wired = _wired()
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/user").mock(return_value=httpx.Response(200, json={"login": "octocat", "id": 1}))
        result = CliInvoker().invoke(
            wired.meta, ["whoami", "--format", "raw", "--columns", "login"]
        )
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "octocat"

    help_result = CliInvoker().invoke(wired.meta, ["--help"])
    assert help_result.exit_code == 0, help_result.output
    for command in ("repos", "search", "sweep", "cache"):
        assert command in help_result.stdout


def test_config_group_lists_and_redacts_github_settings(_isolate: Path) -> None:
    _isolate.write_text(
        "profiles:\n  default:\n    github:\n      token: ghp_secret\n", encoding="utf-8"
    )
    get_settings.cache_clear()
    wired = _wired()
    result = CliInvoker().invoke(
        wired.meta,
        ["config", "list", "--format", "raw", "--columns", "key", "--columns", "value"],
    )
    assert result.exit_code == 0, result.output
    assert "github.token" in result.stdout
    assert "ghp_secret" not in result.stdout


def test_profile_group_and_flag_resolve(_isolate: Path) -> None:
    _isolate.write_text(
        "profiles:\n  work:\n    github:\n      token: WT\nactive: work\n", encoding="utf-8"
    )
    get_settings.cache_clear()
    wired = _wired()
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/user").mock(return_value=httpx.Response(200, json={"login": "wuser", "id": 2}))
        result = CliInvoker().invoke(
            wired.meta, ["whoami", "--format", "raw", "--columns", "login", "--profile", "work"]
        )
    assert result.exit_code == 0, result.output


def test_program_name_is_tool_command(_isolate: Path) -> None:
    wired = _wired()
    result = CliInvoker().invoke(wired.meta, ["--help"])
    assert "untaped-github" in result.output
