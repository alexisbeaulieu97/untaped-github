"""Release workflow checks for untaped-github."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9][A-Za-z0-9._+-]*)?")


class ReleaseCheckError(RuntimeError):
    """A release precondition failed."""


def verify_version(version: str, *, pyproject_path: Path = PYPROJECT) -> None:
    """Verify the requested release version is safe and matches project metadata."""
    if VERSION_RE.fullmatch(version) is None:
        raise ReleaseCheckError(f"unsafe or invalid release version input: {version!r}")

    project = _project_metadata(pyproject_path)
    actual = str(project["version"])
    if actual != version:
        raise ReleaseCheckError(
            f"workflow input version {version!r} does not match pyproject.toml {actual!r}"
        )
    print(f"ok: package metadata version matches workflow input {version}")


def verify_target_unused(version: str) -> None:
    """Fail closed if the production GitHub release or tag already exists."""
    check_github_release_absent(version)
    check_git_tag_absent(version)


def check_github_release_absent(
    version: str,
    *,
    repo: str | None = None,
    token: str | None = None,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> None:
    """Fail closed unless GitHub proves the release tag is absent."""
    repo = repo or os.environ.get("GITHUB_REPOSITORY")
    token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not repo:
        raise ReleaseCheckError("could not verify GitHub release: GITHUB_REPOSITORY is missing")
    if not token:
        raise ReleaseCheckError("could not verify GitHub release: GH_TOKEN is missing")

    quoted_tag = urllib.parse.quote(f"v{version}", safe="")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/tags/{quoted_tag}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            status = int(getattr(response, "status", 0))
            if status == 200:
                raise ReleaseCheckError(f"GitHub release v{version} already exists.")
            raise ReleaseCheckError(
                f"could not verify GitHub release v{version}: unexpected HTTP {status}"
            )
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return
        raise ReleaseCheckError(
            f"could not verify GitHub release v{version}: HTTP {error.code}"
        ) from error
    except urllib.error.URLError as error:
        raise ReleaseCheckError(f"could not verify GitHub release v{version}: {error}") from error


def check_git_tag_absent(
    version: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Fail closed unless git proves the remote tag is absent."""
    command = [
        "git",
        "ls-remote",
        "--exit-code",
        "--tags",
        "origin",
        f"refs/tags/v{version}",
    ]
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode == 0:
        raise ReleaseCheckError(f"Git tag v{version} already exists on origin.")
    if completed.returncode == 2:
        return

    detail = completed.stderr.strip() or completed.stdout.strip()
    suffix = f": {detail}" if detail else ""
    raise ReleaseCheckError(
        f"could not verify Git tag v{version}: git ls-remote exited {completed.returncode}{suffix}"
    )


def verify_sdk_published(
    index: str,
    *,
    pyproject_path: Path = PYPROJECT,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Verify the configured SDK requirement resolves from the selected install path."""
    requirement = sdk_requirement(pyproject_path)
    env = os.environ.copy()
    if index == "testpypi":
        env["UV_INDEX"] = "https://test.pypi.org/simple/"
        env["UV_INDEX_STRATEGY"] = "unsafe-best-match"
    elif index != "pypi":
        raise ReleaseCheckError(f"unknown release index: {index}")

    command = [
        "uv",
        "run",
        "--no-project",
        "--refresh-package",
        "untaped",
        "--with",
        requirement,
        "python",
        "-c",
        "import importlib.metadata as m; print(m.version('untaped'))",
    ]
    completed = runner(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ReleaseCheckError(f"{requirement} is not available from {index}: {detail}")
    print(f"ok: {requirement} resolves from {index}")


def sdk_requirement(pyproject_path: Path = PYPROJECT) -> str:
    """Return the untaped SDK requirement from project dependencies."""
    for dependency in _project_metadata(pyproject_path)["dependencies"]:
        if _dependency_name(str(dependency)) == "untaped":
            return str(dependency)
    raise ReleaseCheckError("pyproject.toml does not declare an untaped dependency")


def _dependency_name(requirement: str) -> str:
    match = re.match(r"([A-Za-z0-9_.-]+)", requirement)
    if match is None:
        return ""
    return match.group(1).replace("_", "-").replace(".", "-").lower()


def _project_metadata(pyproject_path: Path) -> dict[str, Any]:
    return tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]


def main(argv: list[str] | None = None) -> int:
    """Run release checks from the command line."""
    parser = argparse.ArgumentParser(description="Run release workflow checks.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_version_parser = subparsers.add_parser("verify-version")
    verify_version_parser.add_argument("version")

    verify_target_parser = subparsers.add_parser("verify-target-unused")
    verify_target_parser.add_argument("version")

    verify_sdk_parser = subparsers.add_parser("verify-sdk-published")
    verify_sdk_parser.add_argument("--index", choices=["testpypi", "pypi"], required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "verify-version":
            verify_version(args.version)
        elif args.command == "verify-target-unused":
            verify_target_unused(args.version)
        elif args.command == "verify-sdk-published":
            verify_sdk_published(args.index)
        else:  # pragma: no cover - argparse enforces choices.
            parser.error(f"unknown command: {args.command}")
    except ReleaseCheckError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
