"""Contract tests for the reusable PyPI release workflow caller."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
CORE_RELEASE_SHA = "45cef5c2c4e2f9057135480f20e183df46d94b99"


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_release_workflow_dispatch_keeps_version_and_index_inputs() -> None:
    dispatch = _workflow()["on"]["workflow_dispatch"]["inputs"]

    assert dispatch == {
        "version": {"required": True, "type": "string"},
        "index": {
            "required": True,
            "type": "choice",
            "options": ["testpypi", "pypi"],
        },
    }


def test_release_workflow_calls_pinned_core_reusable_workflow() -> None:
    workflow = _workflow()
    release = workflow["jobs"]["release"]

    assert workflow["permissions"] == {"contents": "read"}
    assert release["uses"] == (
        f"alexisbeaulieu97/untaped/.github/workflows/pypi-package-release.yml@{CORE_RELEASE_SHA}"
    )
    assert release["with"]["release-tool-ref"] == CORE_RELEASE_SHA
    assert release["uses"].endswith(f"@{release['with']['release-tool-ref']}")
    assert release["with"]["package"] == "untaped-github"
    assert release["with"]["console-script"] == "untaped-github"
    assert release["permissions"] == {"contents": "write", "id-token": "write"}
