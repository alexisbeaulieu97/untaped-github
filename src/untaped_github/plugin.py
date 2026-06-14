"""Untaped plugin manifest for the GitHub domain.

API v5: the plugin object declares ``id``, ``untaped_api_version = 5``, and
returns its contributions as data from ``manifest()``. The CLI is mounted
through a ``CliSpec`` import path so ``untaped --help`` never imports the
GitHub command modules.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from untaped.api import CliSpec, PluginManifest, SkillSpec

from untaped_github.settings import GithubSettings


class GithubPlugin:
    """Entry-point plugin object exposed through ``untaped.plugins``."""

    id = "github"
    untaped_api_version = 5

    def manifest(self) -> PluginManifest:
        """Declare the GitHub CLI, profile settings, and agent skill."""
        return PluginManifest(
            clis=(
                CliSpec(
                    name="github",
                    import_path="untaped_github.cli:app",
                    help="Inspect and search GitHub from the authenticated user's account.",
                ),
            ),
            profile_settings={"github": GithubSettings},
            skills=(
                SkillSpec(
                    name="untaped-github",
                    source=Path(str(files("untaped_github").joinpath("skills", "untaped-github"))),
                    description="Use the untaped GitHub plugin.",
                ),
            ),
        )


plugin = GithubPlugin()
