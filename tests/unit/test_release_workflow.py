"""Contract tests for the PyPI/TestPyPI release workflow."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
README = REPO_ROOT / "README.md"
COMMAND_DOC = REPO_ROOT / "docs" / "github.md"
RELEASE_DOC = REPO_ROOT / "docs" / "release.md"
SKILL = REPO_ROOT / "src" / "untaped_github" / "skills" / "untaped-github" / "SKILL.md"

EXPECTED_UV_VERSION = "0.11.26"
EXPECTED_ACTION_REFS = {
    "actions/checkout": "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
    "actions/cache": "55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    "astral-sh/setup-uv": "fac544c07dec837d0ccb6301d7b5580bf5edae39",
    "pypa/gh-action-pypi-publish": "cef221092ed1bacb1cc03d23a2d87d1d172e277b",
}
USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s+([^\s#]+)(?:\s+#.*)?\s*$", re.MULTILINE)
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(_workflow_text())


def _step_block(name: str) -> str:
    text = _workflow_text()
    next_step_or_job = r"(?=^      - name: |^  [a-zA-Z0-9_-]+:|\Z)"
    pattern = rf"(?ms)^      - name: {re.escape(name)}\n.*?{next_step_or_job}"
    match = re.search(pattern, text)
    assert match is not None, f"workflow step not found: {name}"
    return match.group(0)


def _workflow_steps(job_name: str) -> list[dict[str, Any]]:
    return list(_workflow()["jobs"][job_name]["steps"])


def _workflow_step(job_name: str, name: str) -> dict[str, Any]:
    for step in _workflow_steps(job_name):
        if step["name"] == name:
            return step
    raise AssertionError(f"workflow step not found in {job_name}: {name}")


def _unpinned_action_refs(text: str) -> list[str]:
    offenders: list[str] = []
    for action_ref in USES_RE.findall(text):
        if "@" not in action_ref:
            offenders.append(action_ref)
            continue
        _, ref = action_ref.rsplit("@", maxsplit=1)
        if not FULL_SHA_RE.fullmatch(ref):
            offenders.append(action_ref)
    return offenders


def test_project_metadata_declares_initial_pypi_release_contract() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["version"] == "0.12.5"
    assert project["readme"] == "README.md"
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert "License ::" not in "\n".join(project.get("classifiers", []))
    assert "untaped>=2.4.4,<3" in project["dependencies"]
    assert pyproject["tool"]["uv"]["sources"]["untaped"]["rev"] == "v2.4.4"


def test_release_workflow_dispatch_concurrency_and_permissions() -> None:
    workflow = _workflow()

    dispatch = workflow["on"]["workflow_dispatch"]["inputs"]
    assert dispatch["version"]["type"] == "string"
    assert dispatch["index"]["options"] == ["testpypi", "pypi"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "${{ github.workflow }}-${{ inputs.index }}-${{ inputs.version }}",
        "cancel-in-progress": False,
    }

    jobs = workflow["jobs"]
    assert jobs["build"]["permissions"] == {"contents": "read"}
    assert "id-token" not in jobs["build"]["permissions"]
    assert "environment" not in jobs["build"]

    assert jobs["publish"]["needs"] == "build"
    assert jobs["publish"]["environment"] == "${{ inputs.index }}"
    assert jobs["publish"]["permissions"] == {"contents": "read", "id-token": "write"}

    assert jobs["smoke-published"]["needs"] == "publish"
    assert jobs["smoke-published"]["permissions"] == {"contents": "read"}
    assert "id-token" not in jobs["smoke-published"]["permissions"]
    assert "environment" not in jobs["smoke-published"]

    assert jobs["github-release"]["needs"] == "smoke-published"
    assert jobs["github-release"]["if"] == "inputs.index == 'pypi'"
    assert jobs["github-release"]["permissions"] == {"contents": "write"}
    assert "id-token" not in jobs["github-release"]["permissions"]
    assert "environment" not in jobs["github-release"]


def test_release_workflow_uses_latest_reviewed_action_shas() -> None:
    text = _workflow_text()
    offenders: list[str] = []
    unpinned = _unpinned_action_refs(text)
    assert not unpinned, "release workflow actions must be pinned to full SHAs:\n" + "\n".join(
        unpinned
    )

    refs = USES_RE.findall(text)
    assert refs, "release workflow must use pinned actions"
    for action_ref in refs:
        action, ref = action_ref.rsplit("@", maxsplit=1)
        expected = EXPECTED_ACTION_REFS.get(action)
        if expected is None:
            offenders.append(f"unreviewed action {action}")
        elif ref != expected:
            offenders.append(f"{action}@{ref} does not match reviewed SHA {expected}")

    assert not offenders, "GitHub Action pins are stale:\n" + "\n".join(offenders)


def test_action_ref_parser_catches_mutable_and_missing_refs() -> None:
    sha = "a" * 40
    workflow = f"""
      - uses: actions/checkout@{sha}
      - uses: astral-sh/setup-uv@v8
      - uses: actions/cache
"""

    assert _unpinned_action_refs(workflow) == ["astral-sh/setup-uv@v8", "actions/cache"]


def test_release_checkout_does_not_persist_credentials() -> None:
    checkout = _workflow_step("build", "Checkout")

    assert checkout["uses"] == f"actions/checkout@{EXPECTED_ACTION_REFS['actions/checkout']}"
    assert checkout["with"]["persist-credentials"] is False


def test_release_workflow_keeps_anti_burn_guards() -> None:
    text = _workflow_text()

    production_guard = _step_block("Guard production publish")
    assert "if: inputs.index == 'pypi'" in production_guard
    assert "refs/heads/main" in production_guard
    assert "exit 1" in production_guard

    version_guard = _step_block("Verify release version")
    assert 'uv run python scripts/release.py verify-version "$RELEASE_VERSION"' in version_guard

    unused_guard = _step_block("Verify production release target is unused")
    assert "if: inputs.index == 'pypi'" in unused_guard
    assert (
        'uv run python scripts/release.py verify-target-unused "$RELEASE_VERSION"' in unused_guard
    )

    step_pattern = r"(?ms)^      - name: .+?(?=^      - name: |^  [a-zA-Z0-9_-]+:|\Z)"
    run_blocks = "\n".join(
        match.group(0) for match in re.finditer(step_pattern, text) if "run:" in match.group(0)
    )
    assert "${{ inputs.version }}" not in run_blocks


def test_release_workflow_validates_build_and_tool_local_wheel_smoke() -> None:
    text = _workflow_text()

    assert "uv sync --frozen" in text
    assert "uv run pre-commit run --all-files --show-diff-on-failure" in text
    assert "uv run mypy" in text
    assert "uv run pytest" in text
    assert "uv build --no-sources" in text

    smoke = _step_block("Smoke local wheel")
    assert "uv venv" in smoke
    assert "uv pip install" in smoke
    assert "dist/*.whl" in smoke
    assert "bin/untaped-github" in smoke
    assert '"$RUNNER_TEMP/local-wheel/bin/untaped-github" --help' in smoke
    assert "untaped.api" not in smoke
    assert 'bin/untaped"' not in smoke


def test_release_workflow_checks_sdk_floor_on_selected_index() -> None:
    sdk_check = _step_block("Verify SDK dependency resolves from selected index")

    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    sdk_requirement = next(dep for dep in project["dependencies"] if dep.startswith("untaped"))
    assert sdk_requirement == "untaped>=2.4.4,<3"
    assert (
        'uv run python scripts/release.py verify-sdk-published --index "$RELEASE_INDEX"'
        in sdk_check
    )
    assert sdk_requirement not in sdk_check
    assert "version may be burned" not in sdk_check.lower()


def test_release_workflow_hands_artifacts_to_trusted_publisher() -> None:
    text = _workflow_text()

    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in text
    assert "name: python-package-distributions" in text
    assert "path: dist/" in text
    assert "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b" in text
    assert "repository-url: https://test.pypi.org/legacy/" in text
    assert "attestations: true" in text
    assert "uv publish" not in text


def test_release_workflow_smokes_published_tool_from_selected_index() -> None:
    smoke = _step_block("Smoke published package")

    assert "UV_INDEX=https://test.pypi.org/simple/" in smoke
    assert "UV_INDEX_STRATEGY=unsafe-best-match" in smoke
    assert "--refresh-package untaped-github" in smoke
    assert "untaped-github==$RELEASE_VERSION" in smoke
    assert 'untaped-github" --help' in smoke
    assert "version may be burned" in smoke.lower()
    assert "bump patch" in smoke.lower()
    assert "untaped.api" not in smoke


def test_release_workflow_creates_github_release_only_after_pypi_smoke() -> None:
    text = _workflow_text()
    release = _step_block("Create GitHub release")

    assert "needs: smoke-published" in text
    assert "if: inputs.index == 'pypi'" in text
    assert "gh release create" in release
    assert ' --repo "$GITHUB_REPOSITORY"' in release
    assert "v$RELEASE_VERSION" in release
    assert "untaped-github v$RELEASE_VERSION" in release


def test_release_docs_and_skill_prefer_pypi_install_and_explain_recovery() -> None:
    for path in (README, COMMAND_DOC, SKILL):
        text = path.read_text(encoding="utf-8")
        assert "uv tool install untaped-github" in text
        assert "git+https://github.com/alexisbeaulieu97/untaped-github.git" in text
        assert "first PyPI release" in text

    release_doc = RELEASE_DOC.read_text(encoding="utf-8")
    normalized_release_doc = " ".join(release_doc.split())
    assert "Trusted Publisher" in release_doc
    assert "testpypi" in release_doc
    assert "pypi" in release_doc
    assert "burned" in release_doc
    assert "Do not rerun" in release_doc
    assert "TestPyPI publishes and smokes only" in release_doc
    assert "PyPI publishes, smokes, then creates the GitHub tag/release" in normalized_release_doc
