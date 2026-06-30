"""Settings for the GitHub tool."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, SecretStr


class GithubSettings(BaseModel):
    """GitHub API settings."""

    base_url: str = "https://api.github.com"
    token: SecretStr | None = None
    corpus_path: Path = Path("~/.untaped/github-corpus")
