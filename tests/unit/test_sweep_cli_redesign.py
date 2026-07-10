"""CLI contract tests for the question-first sweep sub-app."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from untaped.settings import get_settings, register_profile_settings
from untaped.testing import CliInvoker

from untaped_github.cli import app
from untaped_github.settings import GithubSettings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    register_profile_settings("github", GithubSettings)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.yml"
    config.write_text(
        "profiles:\n"
        "  default:\n"
        "    github:\n"
        f"      corpus_path: {tmp_path / 'corpus'}\n"
        "      sweep:\n"
        "        fetch_depth: 7\n"
        "        sync_concurrency: 3\n"
        "        max_age_seconds: 99\n"
    )
    monkeypatch.setenv("UNTAPED_CONFIG", str(config))


def test_sweep_help_exposes_only_question_first_commands() -> None:
    result = CliInvoker().invoke(app, ["sweep", "--help"])

    assert result.exit_code == 0, result.output
    assert "content" in result.stdout
    assert "paths" in result.stdout
    for removed in ("--grep", "--show", "--owners", "--depth", "--parallel"):
        assert removed not in result.stdout


@pytest.mark.parametrize("command", ["content", "paths"])
def test_target_help_has_ordered_groups_and_config_only_tuning(command: str) -> None:
    positional = "REGEX" if command == "content" else "GLOB"
    result = CliInvoker().invoke(app, ["sweep", command, "--help"])

    assert result.exit_code == 0, result.output
    positions = [
        result.stdout.index(f"╭─ {group}")
        for group in (
            "Scope",
            "Constraints",
            "Content matching",
            "Revisions",
            "Freshness",
            "Report",
            "Exit policy",
        )
    ]
    assert positions == sorted(positions)
    assert positional in result.stdout
    assert "--include-archived" in result.stdout
    assert "--include-path" in result.stdout
    assert ".github/**" in result.stdout
    assert "--refresh" in result.stdout and "--cached" in result.stdout
    assert "refreshes uncached, stale, or under-profiled repositories" in result.stdout
    assert "--require-complete" in result.stdout
    assert "--empty-" not in result.stdout
    assert f"--{positional.lower()}" not in result.stdout
    assert "--depth" not in result.stdout and "--parallel" not in result.stdout
    if command == "content":
        assert "--context" in result.stdout
    else:
        assert "--context" not in result.stdout


@pytest.mark.parametrize(
    ("old", "replacement"),
    [
        ("--grep", "sweep content"),
        ("--has-file", "sweep paths"),
        ("--strict", "--require-complete"),
        ("--sync", "--refresh"),
        ("--no-sync", "--cached"),
        ("--archived", "--include-archived"),
        ("--not-grep", "--without-content"),
        ("--lacks-file", "--without-path"),
        ("--path", "--include-path"),
        ("--any", "conjunctive"),
        ("--show", "complete report"),
        ("--owners", "always resolved"),
        ("--no-owners", "always resolved"),
        ("--depth", "github.sweep.fetch_depth"),
        ("--parallel", "github.sweep.sync_concurrency"),
    ],
)
def test_old_root_syntax_has_migration_error(old: str, replacement: str) -> None:
    result = CliInvoker().invoke(app, ["sweep", old, "value"])

    assert result.exit_code == 2
    assert replacement in result.output


@pytest.mark.parametrize(
    ("args", "replacement"),
    [
        (["--org", "acme", "--grep", "TODO"], "sweep content"),
        (
            [
                "--repo",
                "acme/api",
                "--refs",
                "branches",
                "--format",
                "json",
                "--has-file",
                "README.md",
            ],
            "sweep paths",
        ),
        (
            ["--org", "acme", "--ref", "release/*", "--strict", "--grep", "TODO"],
            "sweep content",
        ),
    ],
)
def test_realistic_old_flat_invocation_reaches_migration_guidance(
    args: list[str], replacement: str
) -> None:
    result = CliInvoker().invoke(app, ["sweep", *args])

    assert result.exit_code == 2
    assert replacement in result.output
    assert "Unknown option" not in result.output


@pytest.mark.parametrize(
    ("command", "value", "label"),
    [
        ("content", "TODO\nDONE", "REGEX"),
        ("content", "TODO\rDONE", "REGEX"),
        ("paths", "src\nREADME", "GLOB"),
        ("paths", "src\rREADME", "GLOB"),
    ],
)
def test_primary_actual_newline_is_a_config_error(
    configured: None, command: str, value: str, label: str
) -> None:
    result = CliInvoker().invoke(app, ["sweep", command, value, "--repo", "acme/api", "--cached"])

    assert result.exit_code == 1
    assert f"{label} {value!r}" in result.output
    assert "actual newline" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    ("option", "value"),
    [
        (option, value)
        for option in ("--with-content", "--without-content", "--with-path", "--without-path")
        for value in ("bad\npattern", "bad\rpattern")
    ],
)
def test_constraint_actual_newline_is_a_config_error(
    configured: None, option: str, value: str
) -> None:
    result = CliInvoker().invoke(
        app,
        ["sweep", "content", "TODO", "--repo", "acme/api", option, value, "--cached"],
    )

    assert result.exit_code == 1
    assert f"{option} {value!r}" in result.output
    assert "actual newline" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    ("option", "value"),
    [
        (option, value)
        for option in ("--include-path", "--exclude-path")
        for value in ("src\ntests", "src\rtests")
    ],
)
def test_content_filter_actual_newline_is_a_config_error(
    configured: None, option: str, value: str
) -> None:
    result = CliInvoker().invoke(
        app,
        ["sweep", "content", "TODO", "--repo", "acme/api", option, value, "--cached"],
    )

    assert result.exit_code == 1
    assert f"{option} {value!r}" in result.output
    assert "actual newline" in result.output
    assert "Traceback" not in result.output


def test_scope_is_required(configured: None) -> None:
    result = CliInvoker().invoke(app, ["sweep", "content", "TODO"])

    assert result.exit_code == 2
    assert "--org, --team, --repo, or --stdin" in result.output


def test_refresh_and_cached_are_mutually_exclusive(configured: None) -> None:
    result = CliInvoker().invoke(
        app,
        ["sweep", "paths", "README.md", "--repo", "acme/api", "--refresh", "--cached"],
    )

    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


@pytest.mark.parametrize("option", ["--fixed-strings", "--ignore-case", "--word-regexp"])
def test_paths_content_modifier_requires_content_constraint(configured: None, option: str) -> None:
    result = CliInvoker().invoke(app, ["sweep", "paths", "*.py", "--repo", "acme/api", option])

    assert result.exit_code == 2
    assert "requires --with-content or --without-content" in result.output


def test_paths_content_filter_requires_content_constraint(configured: None) -> None:
    result = CliInvoker().invoke(
        app,
        ["sweep", "paths", "*.py", "--repo", "acme/api", "--exclude-path", ".github/**"],
    )

    assert result.exit_code == 2
    assert "requires --with-content or --without-content" in result.output


def test_cached_team_is_rejected_before_network(configured: None) -> None:
    result = CliInvoker().invoke(
        app,
        ["sweep", "content", "TODO", "--team", "acme/platform", "--cached"],
    )

    assert result.exit_code == 2
    assert "cannot resolve from cached corpus metadata" in result.output
