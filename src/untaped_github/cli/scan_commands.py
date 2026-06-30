"""Cyclopts sub-app: ``untaped github scan``."""

from __future__ import annotations

from typing import Annotated

from cyclopts import Parameter, validators
from untaped.api import (
    ColumnsOption,
    ConfigError,
    FormatOption,
    OutputFormat,
    UntapedError,
    app_context,
    clamp_parallel,
    create_app,
    echo,
    emit,
    render_rows,
    report_errors,
)

from untaped_github.application import RepositoryInventoryScope
from untaped_github.cli._client import open_client
from untaped_github.cli._scopes import OrgOption, TeamOption, parse_team_scopes
from untaped_github.settings import GithubSettings

RepoOption = Annotated[
    list[str] | None,
    Parameter(name="--repo", help="Repository owner/name. Repeatable.", consume_multiple=False),
]
PathOption = Annotated[
    list[str] | None,
    Parameter(name="--path", help="Git pathspec to scan. Repeatable.", consume_multiple=False),
]
GlobOption = Annotated[
    list[str] | None,
    Parameter(name="--glob", help="Git glob pathspec to scan. Repeatable.", consume_multiple=False),
]
ParallelOption = Annotated[
    int,
    Parameter(name=["--parallel", "-j"], help="Parallel Git workers."),
]
DepthOption = Annotated[
    int,
    Parameter(
        name="--depth",
        validator=validators.Number(gte=0),
        help="Git fetch depth; 0 is full.",
    ),
]

app = create_app(name="scan", help="Sync and scan a local Git repository corpus.")


@app.command(name="sync")
def sync_command(
    *,
    org: OrgOption = None,
    team: TeamOption = None,
    repo: RepoOption = None,
    depth: DepthOption = 1,
    parallel: ParallelOption = 8,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
) -> None:
    """Clone or refresh default branches in the local scan corpus."""
    from untaped_github.application import SyncCorpus, SyncOptions  # noqa: PLC0415
    from untaped_github.infrastructure import GitCorpusCache  # noqa: PLC0415
    from untaped_github.infrastructure.git_corpus import git_auth_header  # noqa: PLC0415

    with report_errors(), open_client() as (client, ui):
        settings = app_context().section("github", GithubSettings)
        scope = _scope(org=org, team=team, repo=repo)
        workers = _parallel(parallel)
        token = _token(settings)
        with ui.progress("Syncing repository corpus…"):
            result = SyncCorpus(client, GitCorpusCache())(
                scope,
                SyncOptions(
                    root=settings.corpus_path,
                    depth=depth,
                    parallel=workers,
                    auth_header=git_auth_header(token) if token else None,
                ),
            )
        _render_collection(
            [row.model_dump() for row in result.rows],
            failures=result.failures,
            fmt=fmt,
            columns=columns,
            kind="github.corpus_repo",
            empty="No repositories synced. Broaden your scan scopes.",
        )


@app.command(name="grep")
def grep_command(
    pattern: Annotated[str, Parameter(help="Pattern passed to git grep.")],
    *,
    org: OrgOption = None,
    team: TeamOption = None,
    repo: RepoOption = None,
    sync: Annotated[
        bool,
        Parameter(name="--sync", help="Refresh matching repos before grep."),
    ] = False,
    path: PathOption = None,
    glob: GlobOption = None,
    ignore_case: Annotated[bool, Parameter(name=["--ignore-case", "-i"])] = False,
    fixed_strings: Annotated[bool, Parameter(name=["--fixed-strings", "-F"])] = False,
    word_regexp: Annotated[bool, Parameter(name=["--word-regexp", "-w"])] = False,
    depth: DepthOption = 1,
    parallel: ParallelOption = 8,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
) -> None:
    """Search cached default branches with ``git grep``."""
    from untaped_github.application import GrepCorpus, GrepOptions  # noqa: PLC0415
    from untaped_github.infrastructure import GitCorpusCache  # noqa: PLC0415
    from untaped_github.infrastructure.git_corpus import git_auth_header  # noqa: PLC0415

    with report_errors(), open_client() as (client, ui):
        settings = app_context().section("github", GithubSettings)
        scope = _scope(org=org, team=team, repo=repo)
        workers = _parallel(parallel)
        token = _token(settings)
        with ui.progress("Scanning repository corpus…"):
            result = GrepCorpus(client, GitCorpusCache())(
                scope,
                GrepOptions(
                    root=settings.corpus_path,
                    pattern=pattern,
                    sync=sync,
                    paths=tuple(path or ()),
                    globs=tuple(glob or ()),
                    ignore_case=ignore_case,
                    fixed_strings=fixed_strings,
                    word_regexp=word_regexp,
                    depth=depth,
                    parallel=workers,
                    auth_header=git_auth_header(token) if token else None,
                ),
            )
        _render_collection(
            [row.model_dump() for row in result.rows],
            failures=result.failures,
            fmt=fmt,
            columns=columns,
            kind="github.codehit",
            empty="No matches found.",
        )


@app.command(name="worktree")
def worktree_command(
    repo: Annotated[str, Parameter(help="Repository owner/name.")],
    *,
    ref: Annotated[str | None, Parameter(name="--ref", help="Cached ref to materialize.")] = None,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
) -> None:
    """Materialize one cached repo/ref and print the worktree path."""
    from untaped_github.application import WorktreeCorpus  # noqa: PLC0415
    from untaped_github.infrastructure import GitCorpusCache  # noqa: PLC0415

    with report_errors(), open_client() as (client, ui):
        settings = app_context().section("github", GithubSettings)
        with ui.progress("Materializing worktree…"):
            result = WorktreeCorpus(client, GitCorpusCache())(
                repo,
                root=settings.corpus_path,
                ref=ref,
            )
        emit(result, fmt=fmt, columns=columns, kind="github.worktree")


@app.command(name="list")
def list_command(
    *,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
) -> None:
    """List repositories cached in the local scan corpus."""
    from untaped_github.application import ListCorpus  # noqa: PLC0415
    from untaped_github.infrastructure import GitCorpusCache  # noqa: PLC0415

    with report_errors():
        settings = app_context().section("github", GithubSettings)
        rows = [row.model_dump() for row in ListCorpus(GitCorpusCache())(root=settings.corpus_path)]
        rendered = render_rows(
            rows,
            fmt=fmt,
            columns=columns,
            kind="github.corpus_repo",
            empty="No repositories are cached in the local scan corpus.",
        )
        if rendered:
            echo(rendered)


@app.command(name="clean")
def clean_command(
    *,
    repo: RepoOption = None,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
) -> None:
    """Remove repositories from the managed scan corpus."""
    from untaped_github.application import CleanCorpus  # noqa: PLC0415
    from untaped_github.infrastructure import GitCorpusCache  # noqa: PLC0415

    with report_errors():
        settings = app_context().section("github", GithubSettings)
        rows = [
            row.model_dump()
            for row in CleanCorpus(GitCorpusCache())(
                root=settings.corpus_path,
                repos=tuple(repo or ()),
            )
        ]
        rendered = render_rows(
            rows,
            fmt=fmt,
            columns=columns,
            kind="github.corpus_repo",
            empty="No matching repositories were cached.",
        )
        if rendered:
            echo(rendered)


def _scope(
    *,
    org: list[str] | None,
    team: list[str] | None,
    repo: list[str] | None,
) -> RepositoryInventoryScope:
    orgs = tuple(org or ())
    team_scopes = parse_team_scopes(team, orgs=orgs)
    repos = tuple(repo or ())
    if not orgs and not team_scopes and not repos:
        raise ConfigError("scan requires --org, --team, or --repo")
    return RepositoryInventoryScope(orgs=orgs, teams=team_scopes, repos=repos)


def _parallel(value: int) -> int:
    if value < 1:
        raise ConfigError("--parallel must be positive")
    return clamp_parallel(value, cap=32, policy="Git corpus worker cap")


def _token(settings: GithubSettings) -> str:
    if settings.token is None:
        return ""
    return settings.token.get_secret_value().strip()


def _render_collection(
    rows: list[dict[str, object]],
    *,
    failures: tuple[object, ...],
    fmt: OutputFormat,
    columns: list[str] | None,
    kind: str,
    empty: str,
) -> None:
    rendered = render_rows(rows, fmt=fmt, columns=columns, kind=kind, empty=empty)
    if rendered:
        echo(rendered)
    if failures:
        for failure in failures:
            repo = getattr(failure, "repo", "<unknown>")
            reason = getattr(failure, "reason", str(failure))
            echo(f"failed {repo}: {reason}", err=True)
        raise UntapedError(f"scan completed with {len(failures)} repo failure(s)")
