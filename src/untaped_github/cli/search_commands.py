"""Cyclopts sub-app: ``untaped github search``.

Four subcommands, one per GitHub search endpoint. Each builds a frozen
filter object from CLI flags, hands it to its use case, and pipes the
result through core's ``render_rows`` helper. Composition lives here;
the use cases own the orchestration.
"""

from __future__ import annotations

from typing import Annotated, Literal

from cyclopts import Parameter, validators
from untaped.api import (
    ColumnsOption,
    ConfigError,
    FormatOption,
    ProfileOverrideOption,
    create_app,
    echo,
    read_identifiers,
    render_rows,
    report_errors,
)

from untaped_github.application import TeamScope
from untaped_github.cli._client import open_client

# Shared across all four search subcommands. GitHub-specific (the
# 1000-result cap belongs to GitHub, not untaped), so it lives
# here rather than in untaped's option aliases.
SearchLimitOption = Annotated[
    int,
    Parameter(
        name="--limit",
        validator=validators.Number(gte=1),
        help=(
            "Cap result count. GitHub enforces a hard 1000-result cap "
            "on search; pass --limit 1000 to opt into the maximum."
        ),
    ),
]
FreeTextArgument = Annotated[str | None, Parameter(help="Free-text query (passed verbatim).")]
UserOption = Annotated[
    str | None,
    Parameter(name="--user", help="user:<login>. Defaults to @me when no other scope is set."),
]
OrgOption = Annotated[
    list[str] | None,
    Parameter(name="--org", help="GitHub org scope. Repeatable.", consume_multiple=False),
]
TeamOption = Annotated[
    list[str] | None,
    Parameter(name="--team", help="Team ORG/SLUG. Repeatable.", consume_multiple=False),
]
RepoOption = Annotated[
    list[str] | None,
    Parameter(name="--repo", help="repo:owner/name. Repeatable.", consume_multiple=False),
]
RepoStdinOption = Annotated[
    bool,
    Parameter(name="--repo-stdin", help="Read repo scopes from stdin."),
]

app = create_app(
    name="search",
    help="Search GitHub for repos, code, issues, and users.",
)


def _stderr_warn(message: str) -> None:
    echo(f"warning: {message}", err=True)


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


@app.command(name="repos")
def repos_command(
    query: FreeTextArgument = None,
    *,
    user: UserOption = None,
    org: OrgOption = None,
    team: TeamOption = None,
    repo: RepoOption = None,
    repo_stdin: RepoStdinOption = False,
    name: Annotated[
        str | None,
        Parameter(name="--name", help="Match against repo name (in:name)."),
    ] = None,
    language: Annotated[str | None, Parameter(name="--language")] = None,
    archived: Annotated[
        bool | None,
        Parameter(name="--archived", negative="--no-archived"),
    ] = None,
    fork: Annotated[bool | None, Parameter(name="--fork", negative="--no-fork")] = None,
    visibility: Annotated[
        Literal["public", "private"] | None,
        Parameter(name="--visibility"),
    ] = None,
    sort: Annotated[
        Literal["stars", "forks", "help-wanted-issues", "updated"] | None,
        Parameter(name="--sort"),
    ] = None,
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
        echo(render_rows(rows, fmt=fmt, columns=columns))


@app.command(name="code")
def code_command(
    query: FreeTextArgument = None,
    *,
    user: Annotated[str | None, Parameter(name="--user")] = None,
    org: OrgOption = None,
    team: TeamOption = None,
    repo: RepoOption = None,
    repo_stdin: RepoStdinOption = False,
    language: Annotated[str | None, Parameter(name="--language")] = None,
    filename: Annotated[str | None, Parameter(name="--filename")] = None,
    path: Annotated[str | None, Parameter(name="--path")] = None,
    extension: Annotated[str | None, Parameter(name="--extension")] = None,
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
        echo(render_rows(rows, fmt=fmt, columns=columns))


@app.command(name="issues")
def issues_command(
    query: FreeTextArgument = None,
    *,
    user: Annotated[str | None, Parameter(name="--user")] = None,
    org: OrgOption = None,
    team: TeamOption = None,
    repo: RepoOption = None,
    repo_stdin: RepoStdinOption = False,
    state: Annotated[Literal["open", "closed"] | None, Parameter(name="--state")] = None,
    kind: Annotated[Literal["issue", "pr"] | None, Parameter(name="--kind")] = None,
    author: Annotated[str | None, Parameter(name="--author")] = None,
    assignee: Annotated[str | None, Parameter(name="--assignee")] = None,
    label: Annotated[
        list[str] | None,
        Parameter(name="--label", help="Repeatable.", consume_multiple=False),
    ] = None,
    mentions: Annotated[str | None, Parameter(name="--mentions")] = None,
    sort: Annotated[
        Literal["comments", "reactions", "interactions", "created", "updated"] | None,
        Parameter(name="--sort"),
    ] = None,
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
        echo(render_rows(rows, fmt=fmt, columns=columns))


@app.command(name="users")
def users_command(
    query: FreeTextArgument = None,
    *,
    kind: Annotated[Literal["user", "org"] | None, Parameter(name="--kind")] = None,
    location: Annotated[str | None, Parameter(name="--location")] = None,
    language: Annotated[str | None, Parameter(name="--language")] = None,
    sort: Annotated[
        Literal["followers", "repositories", "joined"] | None,
        Parameter(name="--sort"),
    ] = None,
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
        echo(render_rows(rows, fmt=fmt, columns=columns))
