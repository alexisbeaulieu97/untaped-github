"""Typer sub-app: ``untaped github search``.

Four subcommands, one per GitHub search endpoint. Each builds a frozen
filter object from CLI flags, hands it to its use case, and pipes the
result through the package-local row renderer. Composition lives here;
the use cases own the orchestration.
"""

from __future__ import annotations

from typing import Annotated, Literal

import typer
from untaped import (
    ColumnsOption,
    ConfigError,
    FormatOption,
    ProfileOverrideOption,
    read_identifiers,
    report_errors,
)

from untaped_github.application import TeamScope
from untaped_github.cli._client import open_client
from untaped_github.cli._rendering import render_rows

# Shared across all four search subcommands. GitHub-specific (the
# 1000-result cap belongs to GitHub, not untaped), so it lives
# here rather than in untaped's option aliases.
SearchLimitOption = Annotated[
    int,
    typer.Option(
        "--limit",
        min=1,
        help=(
            "Cap result count. GitHub enforces a hard 1000-result cap "
            "on search; pass --limit 1000 to opt into the maximum."
        ),
    ),
]

app = typer.Typer(
    name="search",
    help="Search GitHub for repos, code, issues, and users.",
    no_args_is_help=True,
)


@app.callback()
def _callback() -> None:
    """Search GitHub for repos, code, issues, and users."""


def _stderr_warn(message: str) -> None:
    typer.echo(f"warning: {message}", err=True)


def _parse_team_scopes(values: list[str] | None) -> tuple[TeamScope, ...]:
    """Parse repeatable ``--team`` values into explicit org/slug scopes."""
    scopes: list[TeamScope] = []
    for value in values or ():
        parts = value.split("/")
        if len(parts) != 2 or not all(parts):
            raise ConfigError("--team must be ORG/SLUG")
        org, slug = parts
        scopes.append(TeamScope(org=org, slug=slug))
    return tuple(scopes)


def _repo_scopes(values: list[str] | None, *, repo_stdin: bool) -> tuple[str, ...]:
    """Merge explicit ``--repo`` values with optional stdin repo scopes."""
    repos = list(values or ())
    if repo_stdin:
        repos.extend(read_identifiers([], stdin=True))
    return tuple(repos)


@app.command("repos", no_args_is_help=False)
def repos_command(
    query: str | None = typer.Argument(None, help="Free-text query (passed verbatim)."),
    user: str | None = typer.Option(
        None, "--user", help="user:<login>. Defaults to @me when no other scope is set."
    ),
    org: list[str] | None = typer.Option(None, "--org", help="org:<name>. Repeatable."),
    team: list[str] | None = typer.Option(
        None,
        "--team",
        help="Team ORG/SLUG. Repeatable.",
    ),
    repo: list[str] | None = typer.Option(None, "--repo", help="repo:owner/name. Repeatable."),
    repo_stdin: bool = typer.Option(False, "--repo-stdin", help="Read repo scopes from stdin."),
    name: str | None = typer.Option(None, "--name", help="Match against repo name (in:name)."),
    language: str | None = typer.Option(None, "--language"),
    archived: bool | None = typer.Option(None, "--archived/--no-archived"),
    fork: bool | None = typer.Option(None, "--fork/--no-fork"),
    visibility: Literal["public", "private"] | None = typer.Option(None, "--visibility"),
    sort: Literal["stars", "forks", "help-wanted-issues", "updated"] | None = typer.Option(
        None, "--sort"
    ),
    limit: SearchLimitOption = 30,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
    profile: ProfileOverrideOption = None,
) -> None:
    """Search repositories (``GET /search/repositories``)."""
    from untaped_github.application import SearchRepos  # noqa: PLC0415
    from untaped_github.domain import RepoSearchFilters  # noqa: PLC0415

    with report_errors():
        filters = RepoSearchFilters(
            raw_query=query,
            user=user,
            orgs=tuple(org or ()),
            repos=_repo_scopes(repo, repo_stdin=repo_stdin),
            name=name,
            language=language,
            archived=archived,
            fork=fork,
            visibility=visibility,
            sort=sort,
            limit=limit,
        )
        with open_client(profile) as client:
            use_case = SearchRepos(client, client, warn=_stderr_warn)
            team_scopes = _parse_team_scopes(team)
            rows = [r.model_dump() for r in use_case(filters, team_scopes=team_scopes)]
        typer.echo(render_rows(rows, fmt=fmt, columns=columns))


@app.command("code", no_args_is_help=False)
def code_command(
    query: str | None = typer.Argument(None, help="Free-text query (passed verbatim)."),
    user: str | None = typer.Option(None, "--user"),
    org: list[str] | None = typer.Option(None, "--org", help="Repeatable."),
    team: list[str] | None = typer.Option(None, "--team", help="Team ORG/SLUG. Repeatable."),
    repo: list[str] | None = typer.Option(None, "--repo", help="Repeatable."),
    repo_stdin: bool = typer.Option(False, "--repo-stdin", help="Read repo scopes from stdin."),
    language: str | None = typer.Option(None, "--language"),
    filename: str | None = typer.Option(None, "--filename"),
    path: str | None = typer.Option(None, "--path"),
    extension: str | None = typer.Option(None, "--extension"),
    limit: SearchLimitOption = 30,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
    profile: ProfileOverrideOption = None,
) -> None:
    """Search code (``GET /search/code``).

    Requires at least one scope qualifier on the GitHub side; this
    command injects ``user:@me`` if you pass none. GitHub no longer
    supports ``sort`` for code search — best-match is the only order.
    """
    from untaped_github.application import SearchCode  # noqa: PLC0415
    from untaped_github.domain import CodeSearchFilters  # noqa: PLC0415

    with report_errors():
        filters = CodeSearchFilters(
            raw_query=query,
            user=user,
            orgs=tuple(org or ()),
            repos=_repo_scopes(repo, repo_stdin=repo_stdin),
            language=language,
            filename=filename,
            path=path,
            extension=extension,
            limit=limit,
        )
        with open_client(profile) as client:
            use_case = SearchCode(client, client, warn=_stderr_warn)
            team_scopes = _parse_team_scopes(team)
            rows = [r.model_dump() for r in use_case(filters, team_scopes=team_scopes)]
        typer.echo(render_rows(rows, fmt=fmt, columns=columns))


@app.command("issues", no_args_is_help=False)
def issues_command(
    query: str | None = typer.Argument(None, help="Free-text query (passed verbatim)."),
    user: str | None = typer.Option(None, "--user"),
    org: list[str] | None = typer.Option(None, "--org", help="Repeatable."),
    team: list[str] | None = typer.Option(None, "--team", help="Team ORG/SLUG. Repeatable."),
    repo: list[str] | None = typer.Option(None, "--repo", help="Repeatable."),
    repo_stdin: bool = typer.Option(False, "--repo-stdin", help="Read repo scopes from stdin."),
    state: Literal["open", "closed"] | None = typer.Option(None, "--state"),
    kind: Literal["issue", "pr"] | None = typer.Option(None, "--kind"),
    author: str | None = typer.Option(None, "--author"),
    assignee: str | None = typer.Option(None, "--assignee"),
    label: list[str] | None = typer.Option(None, "--label", help="Repeatable."),
    mentions: str | None = typer.Option(None, "--mentions"),
    sort: Literal["comments", "reactions", "interactions", "created", "updated"]
    | None = typer.Option(None, "--sort"),
    limit: SearchLimitOption = 30,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
    profile: ProfileOverrideOption = None,
) -> None:
    """Search issues and pull requests (``GET /search/issues``)."""
    from untaped_github.application import SearchIssues  # noqa: PLC0415
    from untaped_github.domain import IssueSearchFilters  # noqa: PLC0415

    with report_errors():
        filters = IssueSearchFilters(
            raw_query=query,
            user=user,
            orgs=tuple(org or ()),
            repos=_repo_scopes(repo, repo_stdin=repo_stdin),
            state=state,
            kind=kind,
            author=author,
            assignee=assignee,
            labels=tuple(label or ()),
            mentions=mentions,
            sort=sort,
            limit=limit,
        )
        with open_client(profile) as client:
            use_case = SearchIssues(client, client, warn=_stderr_warn)
            team_scopes = _parse_team_scopes(team)
            rows = [r.model_dump() for r in use_case(filters, team_scopes=team_scopes)]
        typer.echo(render_rows(rows, fmt=fmt, columns=columns))


@app.command("users", no_args_is_help=False)
def users_command(
    query: str | None = typer.Argument(None, help="Free-text query (passed verbatim)."),
    kind: Literal["user", "org"] | None = typer.Option(None, "--kind"),
    location: str | None = typer.Option(None, "--location"),
    language: str | None = typer.Option(None, "--language"),
    sort: Literal["followers", "repositories", "joined"] | None = typer.Option(None, "--sort"),
    limit: SearchLimitOption = 30,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
    profile: ProfileOverrideOption = None,
) -> None:
    """Search users and organizations (``GET /search/users``)."""
    from untaped_github.application import SearchUsers  # noqa: PLC0415
    from untaped_github.domain import UserSearchFilters  # noqa: PLC0415

    with report_errors():
        filters = UserSearchFilters(
            raw_query=query,
            kind=kind,
            location=location,
            language=language,
            sort=sort,
            limit=limit,
        )
        with open_client(profile) as client:
            rows = [r.model_dump() for r in SearchUsers(client)(filters)]
        typer.echo(render_rows(rows, fmt=fmt, columns=columns))
