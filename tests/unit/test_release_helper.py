"""Unit tests for release workflow helper logic."""

from __future__ import annotations

import importlib.util
import subprocess
import urllib.error
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "release.py"


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("untaped_github_release_helper", HELPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pyproject(tmp_path: Path, dependency: str = "untaped>=2.4.4,<3") -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        "\n".join(
            [
                "[project]",
                'name = "untaped-github"',
                'version = "0.12.5"',
                "dependencies = [",
                f'    "{dependency}",',
                "]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return b""


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.github.com/repos/alexisbeaulieu97/untaped-github/releases/tags/v0.12.5",
        code=code,
        msg="status",
        hdrs=None,
        fp=None,
    )


def test_verify_version_matches_pyproject_and_rejects_unsafe_input(tmp_path: Path) -> None:
    release = _load_helper()
    pyproject = _pyproject(tmp_path)

    release.verify_version("0.12.5", pyproject_path=pyproject)

    with pytest.raises(release.ReleaseCheckError, match="does not match"):
        release.verify_version("0.12.6", pyproject_path=pyproject)
    with pytest.raises(release.ReleaseCheckError, match="unsafe or invalid"):
        release.verify_version("0.12.5; echo injected", pyproject_path=pyproject)


def test_github_release_check_fails_when_release_exists() -> None:
    release = _load_helper()

    with pytest.raises(release.ReleaseCheckError, match="already exists"):
        release.check_github_release_absent(
            "0.12.5",
            repo="alexisbeaulieu97/untaped-github",
            token="token",
            urlopen=lambda _request, timeout: _Response(200),
        )


def test_github_release_check_accepts_404_as_absent() -> None:
    release = _load_helper()

    def raise_not_found(_request: object, timeout: int) -> object:
        raise _http_error(404)

    release.check_github_release_absent(
        "0.12.5",
        repo="alexisbeaulieu97/untaped-github",
        token="token",
        urlopen=raise_not_found,
    )


def test_github_release_check_fails_closed_on_unexpected_http_status() -> None:
    release = _load_helper()

    def raise_forbidden(_request: object, timeout: int) -> object:
        raise _http_error(403)

    with pytest.raises(release.ReleaseCheckError, match="could not verify"):
        release.check_github_release_absent(
            "0.12.5",
            repo="alexisbeaulieu97/untaped-github",
            token="token",
            urlopen=raise_forbidden,
        )


def test_github_release_check_fails_closed_on_network_error() -> None:
    release = _load_helper()

    def raise_network_error(_request: object, timeout: int) -> object:
        raise urllib.error.URLError("dns failed")

    with pytest.raises(release.ReleaseCheckError, match="could not verify"):
        release.check_github_release_absent(
            "0.12.5",
            repo="alexisbeaulieu97/untaped-github",
            token="token",
            urlopen=raise_network_error,
        )


def test_git_tag_check_maps_exit_codes_fail_closed() -> None:
    release = _load_helper()
    calls: list[list[str]] = []

    def runner(returncode: int) -> Any:
        def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, returncode, "", "stderr")

        return run

    with pytest.raises(release.ReleaseCheckError, match="already exists"):
        release.check_git_tag_absent("0.12.5", runner=runner(0))

    release.check_git_tag_absent("0.12.5", runner=runner(2))

    with pytest.raises(release.ReleaseCheckError, match="could not verify"):
        release.check_git_tag_absent("0.12.5", runner=runner(128))

    assert calls[0] == [
        "git",
        "ls-remote",
        "--exit-code",
        "--tags",
        "origin",
        "refs/tags/v0.12.5",
    ]


def test_sdk_requirement_is_read_from_pyproject(tmp_path: Path) -> None:
    release = _load_helper()
    pyproject = _pyproject(tmp_path, "untaped>=2.5.0,<3")

    assert release.sdk_requirement(pyproject) == "untaped>=2.5.0,<3"


def test_verify_sdk_published_uses_testpypi_index_strategy(tmp_path: Path) -> None:
    release = _load_helper()
    pyproject = _pyproject(tmp_path)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def runner(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, env))
        return subprocess.CompletedProcess(command, 0, "2.4.4", "")

    release.verify_sdk_published("testpypi", pyproject_path=pyproject, runner=runner)

    command, env = calls[0]
    assert command[:5] == ["uv", "run", "--no-project", "--refresh-package", "untaped"]
    assert "--with" in command
    assert "untaped>=2.4.4,<3" in command
    assert env["UV_INDEX"] == "https://test.pypi.org/simple/"
    assert env["UV_INDEX_STRATEGY"] == "unsafe-best-match"
