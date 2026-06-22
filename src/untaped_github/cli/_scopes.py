"""Shared CLI scope option aliases and parsers."""

from __future__ import annotations

from typing import Annotated

from cyclopts import Parameter
from untaped.api import ConfigError

from untaped_github.application.scopes import TeamScope

OrgOption = Annotated[
    list[str] | None,
    Parameter(name="--org", help="GitHub org scope. Repeatable.", consume_multiple=False),
]
TeamOption = Annotated[
    list[str] | None,
    Parameter(name="--team", help="Team ORG/SLUG. Repeatable.", consume_multiple=False),
]


def parse_team_scopes(values: list[str] | None) -> tuple[TeamScope, ...]:
    """Parse repeatable ``--team`` values into explicit org/slug scopes."""
    scopes: list[TeamScope] = []
    for value in values or ():
        parts = value.split("/")
        if len(parts) != 2 or not all(parts):
            raise ConfigError("--team must be ORG/SLUG")
        org, slug = parts
        scopes.append(TeamScope(org=org, slug=slug))
    return tuple(scopes)
