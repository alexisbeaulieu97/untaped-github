"""Contract tests for the PyPI/TestPyPI release workflow."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

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


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _step_block(name: str) -> str:
    text = _workflow_text()
    next_step_or_job = r"(?=^      - name: |^  [a-zA-Z0-9_-]+:|\Z)"
    pattern = rf"(?ms)^      - name: {re.escape(name)}\n.*?{next_step_or_job}"
    match = re.search(pattern, text)
    assert match is not None, f"workflow step not found: {name}"
    return match.group(0)


def _uses_refs(text: str) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for match in re.finditer(r"^\s*uses:\s+([^@\s]+)@([0-9a-f]{40})\s*$", text, re.MULTILINE):
        refs.append((match.group(1), match.group(2)))
    return refs


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
    text = _workflow_text()

    assert "workflow_dispatch:" in text
    assert "version:" in text
    assert "index:" in text
    assert "- testpypi" in text
    assert "- pypi" in text
    assert "permissions:\n  contents: read" in text
    assert "group: ${{ github.workflow }}-${{ inputs.index }}-${{ inputs.version }}" in text
    assert "cancel-in-progress: false" in text
    assert "environment: ${{ inputs.index }}" in text
    assert "id-token: write" in text


def test_release_workflow_uses_latest_reviewed_action_shas() -> None:
    text = _workflow_text()
    offenders: list[str] = []
    refs = _uses_refs(text)
    assert refs, "release workflow must use pinned actions"
    for action, ref in refs:
        expected = EXPECTED_ACTION_REFS.get(action)
        if expected is None:
            offenders.append(f"unreviewed action {action}")
        elif ref != expected:
            offenders.append(f"{action}@{ref} does not match reviewed SHA {expected}")

    assert not offenders, "GitHub Action pins are stale:\n" + "\n".join(offenders)


def test_release_workflow_keeps_anti_burn_guards() -> None:
    text = _workflow_text()

    production_guard = _step_block("Guard production publish")
    assert "if: inputs.index == 'pypi'" in production_guard
    assert "refs/heads/main" in production_guard
    assert "exit 1" in production_guard

    version_guard = _step_block("Verify release version")
    assert "pyproject.toml" in version_guard
    assert "RELEASE_VERSION" in version_guard
    assert "does not match pyproject.toml" in version_guard

    unused_guard = _step_block("Verify production release target is unused")
    assert "if: inputs.index == 'pypi'" in unused_guard
    assert 'gh release view "v$RELEASE_VERSION"' in unused_guard
    assert 'git ls-remote --exit-code --tags origin "refs/tags/v$RELEASE_VERSION"' in unused_guard
    assert "already exists" in unused_guard

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

    assert "untaped>=2.4.4,<3" in sdk_check
    assert "UV_INDEX=https://test.pypi.org/simple/" in sdk_check
    assert "UV_INDEX_STRATEGY=unsafe-best-match" in sdk_check
    assert "--refresh-package untaped" in sdk_check
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
        assert "git+https://github.com/alexisbeaulieu97/untaped-github.git" not in text

    release_doc = RELEASE_DOC.read_text(encoding="utf-8")
    assert "Trusted Publisher" in release_doc
    assert "testpypi" in release_doc
    assert "pypi" in release_doc
    assert "burned" in release_doc
    assert "Do not rerun" in release_doc
