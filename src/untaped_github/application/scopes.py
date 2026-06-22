"""Shared application scope value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamScope:
    """A GitHub team scoped by owning organization."""

    org: str
    slug: str
