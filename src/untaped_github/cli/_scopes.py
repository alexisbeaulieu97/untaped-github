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
    Parameter(
        name="--team",
        help="Team ORG/SLUG, or SLUG with exactly one --org. Repeatable.",
        consume_multiple=False,
    ),
]


def parse_team_scopes(
    values: list[str] | None, *, orgs: tuple[str, ...] = ()
) -> tuple[TeamScope, ...]:
    """Parse repeatable ``--team`` values into explicit org/slug scopes."""
    scopes: list[TeamScope] = []
    for value in values or ():
        parts = value.split("/")
        if len(parts) == 2 and all(parts):
            org, slug = parts
        elif "/" not in value and value and len(orgs) == 1:
            org = orgs[0]
            slug = value
        else:
            raise ConfigError("--team must be ORG/SLUG unless exactly one --org is provided")
        scopes.append(TeamScope(org=org, slug=slug))
    return tuple(scopes)
