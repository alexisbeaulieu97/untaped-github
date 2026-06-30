"""Domain value objects for local Git corpus operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CorpusFailure:
    """A per-repository corpus failure that does not discard other successes."""

    repo: str
    reason: str


@dataclass(frozen=True)
class CorpusRepoTarget:
    """Repository metadata needed by local Git corpus operations."""

    full_name: str
    default_branch: str | None
    clone_url: str | None = None
    html_url: str | None = None
