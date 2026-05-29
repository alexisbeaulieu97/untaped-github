"""Shared CLI composition-root helper for building :class:`GithubClient`.

Both ``whoami`` and ``search`` go through here so adding a new top-level
command is a one-line composition-root call.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from untaped import get_config_section, get_core_settings, profile_override

from untaped_github.settings import GithubSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from untaped_github.infrastructure import GithubClient


@contextmanager
def open_client(profile: str | None = None) -> Iterator[GithubClient]:
    """Build a :class:`GithubClient` from the cached :class:`Settings`.

    Deferred imports keep the workspace-wide rule about lazy imports on
    CLI startup paths satisfied (the GitHub client's transitive imports
    — httpx, pydantic models, etc. — would otherwise pay on every
    ``untaped --help``).
    """
    from untaped_github.infrastructure import GithubClient  # noqa: PLC0415

    with profile_override(profile):
        settings = get_core_settings()
        with GithubClient(
            get_config_section("github", GithubSettings), http=settings.http
        ) as client:
            yield client
