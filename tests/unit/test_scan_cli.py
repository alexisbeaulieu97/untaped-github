"""End-to-end CLI tests for ``untaped github scan``."""

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


def _repo(full_name: str, source: Path) -> dict[str, object]:
    name = full_name.rsplit("/", 1)[1]
    return {
        "full_name": full_name,
        "name": name,
        "html_url": f"https://github.com/{full_name}",
        "clone_url": source.as_uri(),
        "ssh_url": f"git@github.com:{full_name}.git",
        "default_branch": "main",
        "private": True,
        "archived": False,
        "fork": False,
    }


def test_scan_sync_and_grep_pipe_without_search_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    source = _source_repo(
        tmp_path,
        "api",
        {"workflow.yml": "name: ci\nuses: acme/action@v1\n"},
    )

    with respx.mock(base_url="https://api.github.com", assert_all_called=False) as mock:
        mock.get("/orgs/acme/repos").mock(
            return_value=httpx.Response(200, json=[_repo("acme/api", source)])
        )
        sync = CliInvoker().invoke(
            app,
            ["scan", "sync", "--org", "acme", "--format", "json"],
        )
        grep = CliInvoker().invoke(
            app,
            [
                "scan",
                "grep",
                "acme/action",
                "--org",
                "acme",
                "--format",
                "pipe",
            ],
        )

    assert sync.exit_code == 0, sync.output
    assert json.loads(sync.stdout)[0]["repo"] == "acme/api"
    assert grep.exit_code == 0, grep.output
    [line] = grep.stdout.splitlines()
    envelope = json.loads(line)
    assert envelope["kind"] == "github.codehit"
    assert envelope["record"]["repo"] == "acme/api"
    assert envelope["record"]["path"] == "workflow.yml"
    assert all("/search/" not in str(call.request.url) for call in mock.calls)


def test_scan_grep_sync_refreshes_missing_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    source = _source_repo(tmp_path, "api", {"README.md": "uses: acme/action@v1\n"})

    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/orgs/acme/repos").mock(
            return_value=httpx.Response(200, json=[_repo("acme/api", source)])
        )
        result = CliInvoker().invoke(
            app,
            ["scan", "grep", "acme/action", "--org", "acme", "--sync", "--format", "json"],
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["text"] == "uses: acme/action@v1"


def test_scan_grep_missing_cache_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    source = _source_repo(tmp_path, "api", {"README.md": "uses: acme/action@v1\n"})

    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/orgs/acme/repos").mock(
            return_value=httpx.Response(200, json=[_repo("acme/api", source)])
        )
        result = CliInvoker().invoke(
            app,
            ["scan", "grep", "acme/action", "--org", "acme", "--format", "json"],
        )

    assert result.exit_code != 0
    assert "scan grep --sync" in result.output


def test_scan_list_clean_and_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))
    source = _source_repo(tmp_path, "api", {"README.md": "uses: acme/action@v1\n"})

    with respx.mock(base_url="https://api.github.com", assert_all_called=False) as mock:
        mock.get("/repos/acme/api").mock(
            return_value=httpx.Response(200, json=_repo("acme/api", source))
        )
        mock.get("/orgs/acme/repos").mock(
            return_value=httpx.Response(200, json=[_repo("acme/api", source)])
        )
        sync = CliInvoker().invoke(app, ["scan", "sync", "--org", "acme", "--format", "json"])
        listed = CliInvoker().invoke(app, ["scan", "list", "--format", "json"])
        worktree = CliInvoker().invoke(app, ["scan", "worktree", "acme/api", "--format", "json"])
        cleaned = CliInvoker().invoke(
            app,
            ["scan", "clean", "--repo", "acme/api", "--format", "json"],
        )

    assert sync.exit_code == 0, sync.output
    assert json.loads(listed.stdout)[0]["repo"] == "acme/api"
    worktree_path = Path(json.loads(worktree.stdout)["path"])
    assert (worktree_path / "README.md").is_file()
    assert json.loads(cleaned.stdout)[0]["status"] == "removed"


def test_scan_parallel_help_documents_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTAPED_CONFIG", str(_write_config(tmp_path)))

    result = CliInvoker().invoke(app, ["scan", "sync", "--help"])

    assert result.exit_code == 0, result.output
    assert "--parallel" in result.output
    assert "--team" in result.output
