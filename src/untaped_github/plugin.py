"""Untaped plugin registration for the GitHub domain."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from untaped.plugins import PluginRegistry, SkillSpec

from untaped_github.cli import app
from untaped_github.settings import GithubSettings


class GithubPlugin:
    id = "github"
    untaped_api_version = 1

    def register(self, registry: PluginRegistry) -> None:
        registry.add_profile_settings("github", GithubSettings)
        registry.add_cli("github", app)
        registry.add_skill(
            SkillSpec(
                name="untaped-github",
                source=Path(str(files("untaped_github").joinpath("skills", "untaped-github"))),
                description="Use the untaped GitHub plugin.",
            )
        )


plugin = GithubPlugin()
