"""Console-script entrypoint for the ``untaped-github`` CLI.

``untaped-github`` is a standalone tool built on the untaped SDK: ``main()``
hands the GitHub cyclopts app and a :class:`ToolSpec` to ``run_tool``, which
mounts the shared ``config`` / ``profile`` / ``skills`` groups, wires the
``--profile`` / ``--verbose`` root options, and runs under the SDK's error
contract.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from untaped.api import SkillAsset, ToolSpec, run_tool

from untaped_github.cli import app
from untaped_github.settings import GithubSettings

SPEC = ToolSpec(
    command="untaped-github",
    section="github",
    profile_model=GithubSettings,
    skills=(
        SkillAsset(
            name="untaped-github",
            source=Path(str(files("untaped_github").joinpath("skills", "untaped-github"))),
            description="Use the untaped-github CLI.",
        ),
    ),
)


def main() -> object:
    """Run the ``untaped-github`` CLI."""
    return run_tool(app, SPEC)


if __name__ == "__main__":
    main()
