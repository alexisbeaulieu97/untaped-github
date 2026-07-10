"""Acceptance tests for ``untaped-github sweep content|paths``."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from untaped.settings import get_settings, register_profile_settings
from untaped.testing import CliInvoker

from untaped_github.cli import app
from untaped_github.domain import (
    PathMatch,
    SweepFailure,
    SweepReport,
    SweepResult,
    SweepSummary,
)
from untaped_github.settings import GithubSettings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    register_profile_settings("github", GithubSettings)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write_config(tmp_path: Path, *, sync_concurrency: int = 3) -> Path:
    config = tmp_path / "config.yml"
    config.write_text(
        "profiles:\n"
        "  default:\n"
        "    github:\n"
        f"      corpus_path: {tmp_path / 'corpus'}\n"
        "      sweep:\n"
        "        fetch_depth: 7\n"
        f"        sync_concurrency: {sync_concurrency}\n"
        "        max_age_seconds: 99\n"
    )
    return config


def _capture_sweep(
    monkeypatch: pytest.MonkeyPatch,
    *,
    matching: bool = False,
    failed: bool = False,
) -> list[object]:
    captured: list[object] = []

    class FakeSweep:
        def __init__(self, **kwargs: object) -> None:
            captured.append(kwargs)

        def __call__(self, options: object) -> SweepReport:
            captured.append(options)
            query = options.query  # type: ignore[attr-defined]
            fetched_at = datetime(2026, 7, 10, 12, tzinfo=UTC)
            results = (
                (
                    SweepResult(
                        full_name="acme/api",
                        clone_url="https://github.com/acme/api.git",
                        refs_matched=("refs/heads/main",),
                        matches=(PathMatch(refs=("refs/heads/main",), path="README.md"),),
                        owners=(),
                        synced_at=fetched_at,
                    ),
                )
                if matching
                else ()
            )
            failures = (SweepFailure("acme/api", "prepare", "fetch failed"),) if failed else ()
            prepared = 0 if failed else 1
            return SweepReport(
                query=query,
                results=results,
                failures=failures,
                summary=SweepSummary(
                    selected=1,
                    prepared=prepared,
                    scanned=prepared,
                    matched=len(results),
                    unscanned=len(failures),
                    refreshed=0,
                    cached=prepared,
                    oldest_fetched_at=fetched_at if prepared else None,
                ),
            )

    monkeypatch.setattr("untaped_github.application.Sweep", FakeSweep)
    return captured


def test_content_builds_normalized_query_and_uses_config_tuning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    captured = _capture_sweep(monkeypatch)

    result = CliInvoker().invoke(
        app,
        [
            "sweep",
            "content",
            "TODO",
            "--org",
            "acme",
            "--team",
            "platform",
            "--repo",
            "acme/api",
            "--include-archived",
            "--without-path",
            ".github/**",
            "--with-content",
            "FIXME",
            "--with-path",
            "README.md",
            "--without-content",
            "DONE",
            "--include-path",
            "**",
            "--exclude-path",
            ".github/**",
            "--fixed-strings",
            "--ignore-case",
            "--word-regexp",
            "--refs",
            "branches",
            "--ref",
            "release/*",
            "--cached",
            "--context",
            "2",
            "--format",
            "json",
        ],
    )

    # Cached team is tested as a usage error separately; use an API-free explicit team-free rerun.
    assert result.exit_code == 2
    assert captured == []

    result = CliInvoker().invoke(
        app,
        [
            "sweep",
            "content",
            "TODO",
            "--org",
            "acme",
            "--repo",
            "acme/api",
            "--include-archived",
            "--without-path",
            ".github/**",
            "--with-content",
            "FIXME",
            "--with-path",
            "README.md",
            "--without-content",
            "DONE",
            "--include-path",
            "**",
            "--exclude-path",
            ".github/**",
            "--fixed-strings",
            "--ignore-case",
            "--word-regexp",
            "--refs",
            "branches",
            "--ref",
            "release/*",
            "--cached",
            "--context",
            "2",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    options = captured[-1]
    assert options.fetch_depth == 7  # type: ignore[attr-defined]
    assert options.sync_concurrency == 3  # type: ignore[attr-defined]
    assert options.max_age_seconds == 99  # type: ignore[attr-defined]
    query = options.query  # type: ignore[attr-defined]
    assert query.to_dict() == {
        "scope": {
            "orgs": ["acme"],
            "teams": [],
            "repos": ["acme/api"],
            "stdin": False,
            "include_archived": True,
        },
        "question": {"kind": "content", "pattern": "TODO"},
        "constraints": [
            {"kind": "without_path", "pattern": ".github/**"},
            {"kind": "with_content", "pattern": "FIXME"},
            {"kind": "with_path", "pattern": "README.md"},
            {"kind": "without_content", "pattern": "DONE"},
        ],
        "content_options": {
            "mode": "fixed_strings",
            "ignore_case": True,
            "word_regexp": True,
        },
        "path_filters": {"include": ["**"], "exclude": [".github/**"]},
        "refs": {"profile": "branches", "globs": ["release/*"]},
        "freshness": "cached",
        "context": 2,
    }
    assert json.loads(result.stdout)["query"] == query.to_dict()
    assert "Sweep: 0 matched of 1 scanned" in result.stderr


def test_stdin_repositories_are_deduplicated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    captured = _capture_sweep(monkeypatch)

    result = CliInvoker().invoke(
        app,
        ["sweep", "paths", "README.md", "--stdin", "--cached", "--format", "raw"],
        input="acme/api\nacme/api\nacme/web\n",
    )

    assert result.exit_code == 0, result.output
    assert captured[-1].stdin_repos == ("acme/api", "acme/web")  # type: ignore[attr-defined]


def test_fail_on_match_promotes_exit_after_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    _capture_sweep(monkeypatch, matching=True)

    result = CliInvoker().invoke(
        app,
        [
            "sweep",
            "paths",
            "README.md",
            "--repo",
            "acme/api",
            "--cached",
            "--format",
            "pipe",
            "--fail-on-match",
        ],
    )

    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["kind"] == "github.sweep_result"
    assert envelope["record"]["full_name"] == "acme/api"
    assert "Sweep: 1 matched of 1 scanned" in result.stderr


def test_require_complete_promotes_partial_report_after_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    _capture_sweep(monkeypatch, failed=True)

    result = CliInvoker().invoke(
        app,
        [
            "sweep",
            "paths",
            "README.md",
            "--repo",
            "acme/api",
            "--cached",
            "--format",
            "json",
            "--require-complete",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["failures"][0]["stage"] == "prepare"
    assert "warning: unscanned acme/api (prepare): fetch failed" in result.stderr
    assert "Sweep: 0 matched of 0 scanned; 1 unscanned" in result.stderr


def test_configured_concurrency_clamp_uses_config_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "UNTAPED_CONFIG",
        str(_write_config(tmp_path, sync_concurrency=99)),
    )
    captured = _capture_sweep(monkeypatch)

    result = CliInvoker().invoke(
        app,
        ["sweep", "paths", "README.md", "--repo", "acme/api", "--cached"],
    )

    assert result.exit_code == 0, result.output
    assert captured[-1].sync_concurrency == 32  # type: ignore[attr-defined]
    assert "github.sweep.sync_concurrency 99 clamped to 32" in result.stderr
    assert "--parallel" not in result.stderr
