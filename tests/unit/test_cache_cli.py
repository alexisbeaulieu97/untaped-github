"""End-to-end CLI tests for ``untaped github cache``."""

from __future__ import annotations

import json
import subprocess
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
    register_profile_settings("github", GithubSettings)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yml"
    corpus = tmp_path / "corpus"
    cfg.write_text(
        f"profiles:\n  default:\n    github:\n      token: ghp_test\n      corpus_path: {corpus}\n"
    )
    return cfg


def _git(cwd: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _source_repo(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "a@example.com")
    _git(repo, "config", "user.name", "A")
    _git(repo, "config", "commit.gpgsign", "false")
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


def _repo(full_name: str, source: Path, *, archived: bool = False) -> dict[str, object]:
    name = full_name.rsplit("/", 1)[1]
    return {
        "full_name": full_name,
        "name": name,
        "html_url": f"https://github.com/{full_name}",
        "clone_url": source.as_uri(),
        "ssh_url": f"git@github.com:{full_name}.git",
        "default_branch": "main",
        "private": True,
        "archived": archived,
        "fork": False,
    }


def _populate_cache(tmp_path: Path, repos: list[dict[str, object]]) -> None:
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/orgs/acme/repos").mock(return_value=httpx.Response(200, json=repos))
        result = CliInvoker().invoke(
            app,
            ["sweep", "--org", "acme", "--has-file", "README.md", "--format", "json"],
        )
    assert result.exit_code == 0, result.output


def test_cache_status_reports_profile_disk_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    source = _source_repo(tmp_path, "api", {"README.md": "hello\n"})
    _populate_cache(tmp_path, [_repo("acme/api", source)])

    result = CliInvoker().invoke(app, ["cache", "status", "--format", "json"])

    assert result.exit_code == 0, result.output
    [row] = json.loads(result.stdout)
    assert row["repo"] == "acme/api"
    assert row["profile"] == "default"
    assert row["disk_bytes"] > 0
    assert "Cache: 1 repos" in result.stderr
    assert "oldest" in result.stderr
    assert "newest" in result.stderr


def test_cache_prune_removes_departed_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    api = _source_repo(tmp_path, "api", {"README.md": "hello\n"})
    worker = _source_repo(tmp_path, "worker", {"README.md": "hello\n"})
    _populate_cache(tmp_path, [_repo("acme/api", api), _repo("acme/worker", worker)])

    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/orgs/acme/repos").mock(
            return_value=httpx.Response(200, json=[_repo("acme/api", api)])
        )
        rejected = CliInvoker().invoke(
            app,
            ["cache", "clean", "--prune", "--org", "acme", "--format", "json"],
        )
    listed_after_reject = CliInvoker().invoke(app, ["cache", "status", "--format", "json"])

    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/orgs/acme/repos").mock(
            return_value=httpx.Response(200, json=[_repo("acme/api", api)])
        )
        pruned = CliInvoker().invoke(
            app,
            ["cache", "clean", "--prune", "--org", "acme", "--yes", "--format", "json"],
        )
    listed_after_prune = CliInvoker().invoke(app, ["cache", "status", "--format", "json"])

    assert rejected.exit_code != 0
    assert {row["repo"] for row in json.loads(listed_after_reject.stdout)} == {
        "acme/api",
        "acme/worker",
    }
    assert pruned.exit_code == 0, pruned.output
    assert [row["repo"] for row in json.loads(pruned.stdout)] == ["acme/worker"]
    assert [row["repo"] for row in json.loads(listed_after_prune.stdout)] == ["acme/api"]


def test_cache_clean_requires_exactly_one_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    missing = CliInvoker().invoke(app, ["cache", "clean", "--format", "json"])
    combined = CliInvoker().invoke(
        app,
        ["cache", "clean", "--repo", "acme/api", "--all", "--yes", "--format", "json"],
    )

    assert missing.exit_code != 0
    assert "requires exactly one" in missing.output
    assert combined.exit_code != 0
    assert "requires exactly one" in combined.output


def test_cache_worktree_materializes_cached_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    source = _source_repo(tmp_path, "api", {"README.md": "hello\n"})
    _populate_cache(tmp_path, [_repo("acme/api", source)])

    result = CliInvoker().invoke(app, ["cache", "worktree", "acme/api", "--format", "json"])

    assert result.exit_code == 0, result.output
    row = json.loads(result.stdout)
    assert row["repo"] == "acme/api"
    assert (Path(row["path"]) / "README.md").is_file()
