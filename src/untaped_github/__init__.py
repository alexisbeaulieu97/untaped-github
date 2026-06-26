"""untaped-github: inspect and query GitHub from the untaped SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING

from untaped_github.domain.errors import GithubGraphqlError
from untaped_github.domain.models import BatchRepoRefsResult, RepoRef, RepoRefs
from untaped_github.infrastructure import GithubClient
from untaped_github.settings import GithubSettings

if TYPE_CHECKING:
    from cyclopts import App

__all__ = [
    "BatchRepoRefsResult",
    "GithubClient",
    "GithubGraphqlError",
    "GithubSettings",
    "RepoRef",
    "RepoRefs",
    "app",
]


def __getattr__(name: str) -> App:
    """Lazily re-export the Cyclopts ``app`` (PEP 562).

    The tool entry point mounts the CLI via an import path, so this package
    must not import ``untaped_github.cli`` at import time — that would drag
    the whole command tree onto every ``untaped-github --help`` startup path.
    """
    if name == "app":
        from untaped_github.cli import app  # noqa: PLC0415

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
