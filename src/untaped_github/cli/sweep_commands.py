"""Cyclopts sub-app: ``untaped-github sweep content|paths``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, cast

from cyclopts import Group, Parameter, Token, validators
from untaped.api import (
    ConfigError,
    OutputFormat,
    app_context,
    create_app,
    echo,
    finish,
    raise_usage,
    read_identifiers,
    report_errors,
)

from untaped_github.cli._client import open_client
from untaped_github.cli.sweep_output import emit_sweep_report
from untaped_github.settings import GithubSettings

SCOPE = Group("Scope", sort_key=10)
CONSTRAINTS = Group("Constraints", sort_key=20)
CONTENT = Group("Content matching", sort_key=30)
REVISIONS = Group("Revisions", sort_key=40)
FRESHNESS = Group("Freshness", sort_key=50)
REPORT = Group("Report", sort_key=60)
EXIT_POLICY = Group("Exit policy", sort_key=70)

app = create_app(
    name="sweep",
    help="Ask evidence-first content or path questions across repository refs.",
)

QuestionPattern = Annotated[
    str,
    Parameter(
        group=CONTENT,
        help="Primary matcher; the only source of reported evidence.",
    ),
]
OrgOption = Annotated[
    list[str] | None,
    Parameter(
        name="--org",
        group=SCOPE,
        help="GitHub organization. Repeatable and additive.",
        consume_multiple=False,
        negative_iterable="",
    ),
]
TeamOption = Annotated[
    list[str] | None,
    Parameter(
        name="--team",
        group=SCOPE,
        help="Team ORG/SLUG, or SLUG with exactly one --org. Repeatable and additive.",
        consume_multiple=False,
        negative_iterable="",
    ),
]
RepoOption = Annotated[
    list[str] | None,
    Parameter(
        name="--repo",
        group=SCOPE,
        help="Repository OWNER/NAME. Repeatable and additive.",
        consume_multiple=False,
        negative_iterable="",
    ),
]
StdinOption = Annotated[
    bool,
    Parameter(
        name="--stdin",
        negative="",
        group=SCOPE,
        help="Read bare OWNER/NAME values or full_name pipe records from stdin.",
    ),
]
IncludeArchivedOption = Annotated[
    bool,
    Parameter(
        name="--include-archived",
        negative="",
        group=SCOPE,
        help="Include archived repositories (default: excluded).",
    ),
]
ConstraintKind = Literal["with_content", "without_content", "with_path", "without_path"]
ConstraintInput = tuple[ConstraintKind, str]


def _constraint_converter(
    _type: object,
    tokens: Sequence[Token],
) -> list[ConstraintInput]:
    kinds: dict[str, ConstraintKind] = {
        "--with-content": "with_content",
        "--without-content": "without_content",
        "--with-path": "with_path",
        "--without-path": "without_path",
    }
    return [(kinds[token.keyword or ""], token.value) for token in tokens]


ConstraintOption = Annotated[
    list[ConstraintInput] | None,
    Parameter(
        name=["--with-content", "--without-content", "--with-path", "--without-path"],
        converter=_constraint_converter,
        group=CONSTRAINTS,
        help="Same-ref constraint. Repeatable in stated order; every constraint must pass.",
        consume_multiple=False,
        n_tokens=1,
        negative_iterable="",
    ),
]
IncludePathOption = Annotated[
    list[str] | None,
    Parameter(
        name="--include-path",
        group=CONTENT,
        help="Limit content evaluation to matching paths. Repeatable; e.g. '**'.",
        consume_multiple=False,
        negative_iterable="",
    ),
]
ExcludePathOption = Annotated[
    list[str] | None,
    Parameter(
        name="--exclude-path",
        group=CONTENT,
        help="Exclude content paths; exclusion wins, e.g. '.github/**'. Repeatable.",
        consume_multiple=False,
        negative_iterable="",
    ),
]
FixedStringsOption = Annotated[
    bool,
    Parameter(
        name="--fixed-strings",
        negative="",
        group=CONTENT,
        help="Treat every content pattern literally (default: forced POSIX ERE).",
    ),
]
IgnoreCaseOption = Annotated[
    bool,
    Parameter(
        name="--ignore-case",
        negative="",
        group=CONTENT,
        help="Match every content pattern case-insensitively (default: case-sensitive).",
    ),
]
WordRegexpOption = Annotated[
    bool,
    Parameter(
        name="--word-regexp",
        negative="",
        group=CONTENT,
        help="Require word-boundary matches for every content pattern (default: off).",
    ),
]
RefsOption = Annotated[
    Literal["default", "branches", "tags", "all"],
    Parameter(name="--refs", group=REVISIONS, help="Ref profile (default: default)."),
]
RefOption = Annotated[
    list[str] | None,
    Parameter(
        name="--ref",
        group=REVISIONS,
        help="Additional branch/tag name glob. Repeatable and unioned with --refs.",
        consume_multiple=False,
        negative_iterable="",
    ),
]
RefreshOption = Annotated[
    bool,
    Parameter(
        name="--refresh",
        negative="",
        group=FRESHNESS,
        help=(
            "Force preparation of the selected scope (mutually exclusive with --cached). "
            "Default auto freshness refreshes uncached, stale, or under-profiled repositories."
        ),
    ),
]
CachedOption = Annotated[
    bool,
    Parameter(
        name="--cached",
        negative="",
        group=FRESHNESS,
        help="Use covering corpus state only; make no network calls (rejects --team).",
    ),
]
FormatOption = Annotated[
    OutputFormat,
    Parameter(name=["--format", "-f"], group=REPORT, help="Output format (default: table)."),
]
ColumnsOption = Annotated[
    list[str] | None,
    Parameter(
        name=["--columns", "-c"],
        group=REPORT,
        help="Result columns to include. Repeatable; use '?' to list selectors.",
        consume_multiple=False,
        negative_iterable="",
    ),
]
FailOnMatchOption = Annotated[
    bool,
    Parameter(
        name="--fail-on-match",
        negative="",
        group=EXIT_POLICY,
        help="Exit 1 when at least one repository matches (default: matches exit 0).",
    ),
]
RequireCompleteOption = Annotated[
    bool,
    Parameter(
        name="--require-complete",
        negative="",
        group=EXIT_POLICY,
        help="Exit 1 when any selected repository is unscanned (default: partial reports exit 0).",
    ),
]


@app.command(name="content")
def content_command(
    regex: QuestionPattern,
    /,
    *,
    org: OrgOption = None,
    team: TeamOption = None,
    repo: RepoOption = None,
    stdin: StdinOption = False,
    include_archived: IncludeArchivedOption = False,
    constraint: ConstraintOption = None,
    include_path: IncludePathOption = None,
    exclude_path: ExcludePathOption = None,
    fixed_strings: FixedStringsOption = False,
    ignore_case: IgnoreCaseOption = False,
    word_regexp: WordRegexpOption = False,
    refs: RefsOption = "default",
    ref: RefOption = None,
    refresh: RefreshOption = False,
    cached: CachedOption = False,
    context: Annotated[
        int,
        Parameter(
            name="--context",
            group=REPORT,
            validator=validators.Number(gte=0),
            help="Include N surrounding source lines (default: 0).",
        ),
    ] = 0,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
    fail_on_match: FailOnMatchOption = False,
    require_complete: RequireCompleteOption = False,
) -> None:
    """Report content locations matching REGEX (forced POSIX ERE by default)."""
    _run(
        question_kind="content",
        pattern=regex,
        org=org,
        team=team,
        repo=repo,
        stdin=stdin,
        include_archived=include_archived,
        constraints=constraint,
        include_path=include_path,
        exclude_path=exclude_path,
        fixed_strings=fixed_strings,
        ignore_case=ignore_case,
        word_regexp=word_regexp,
        refs=refs,
        ref=ref,
        refresh=refresh,
        cached=cached,
        context=context,
        fmt=fmt,
        columns=columns,
        fail_on_match=fail_on_match,
        require_complete=require_complete,
    )


@app.command(name="paths")
def paths_command(
    glob: QuestionPattern,
    /,
    *,
    org: OrgOption = None,
    team: TeamOption = None,
    repo: RepoOption = None,
    stdin: StdinOption = False,
    include_archived: IncludeArchivedOption = False,
    constraint: ConstraintOption = None,
    include_path: IncludePathOption = None,
    exclude_path: ExcludePathOption = None,
    fixed_strings: FixedStringsOption = False,
    ignore_case: IgnoreCaseOption = False,
    word_regexp: WordRegexpOption = False,
    refs: RefsOption = "default",
    ref: RefOption = None,
    refresh: RefreshOption = False,
    cached: CachedOption = False,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
    fail_on_match: FailOnMatchOption = False,
    require_complete: RequireCompleteOption = False,
) -> None:
    """Report tracked repository paths matching gitignore-style GLOB."""
    has_content_constraint = any(
        kind in ("with_content", "without_content") for kind, _value in constraint or ()
    )
    if not has_content_constraint and (
        include_path or exclude_path or fixed_strings or ignore_case or word_regexp
    ):
        raise_usage(
            "content matching options on sweep paths requires --with-content or --without-content"
        )
    _run(
        question_kind="path",
        pattern=glob,
        org=org,
        team=team,
        repo=repo,
        stdin=stdin,
        include_archived=include_archived,
        constraints=constraint,
        include_path=include_path,
        exclude_path=exclude_path,
        fixed_strings=fixed_strings,
        ignore_case=ignore_case,
        word_regexp=word_regexp,
        refs=refs,
        ref=ref,
        refresh=refresh,
        cached=cached,
        context=0,
        fmt=fmt,
        columns=columns,
        fail_on_match=fail_on_match,
        require_complete=require_complete,
    )


def _run(
    *,
    question_kind: Literal["content", "path"],
    pattern: str,
    org: list[str] | None,
    team: list[str] | None,
    repo: list[str] | None,
    stdin: bool,
    include_archived: bool,
    constraints: list[ConstraintInput] | None,
    include_path: list[str] | None,
    exclude_path: list[str] | None,
    fixed_strings: bool,
    ignore_case: bool,
    word_regexp: bool,
    refs: Literal["default", "branches", "tags", "all"],
    ref: list[str] | None,
    refresh: bool,
    cached: bool,
    context: int,
    fmt: OutputFormat,
    columns: list[str] | None,
    fail_on_match: bool,
    require_complete: bool,
) -> None:
    from untaped_github.application import (  # noqa: PLC0415
        ResolveRepositoryInventory,
        Sweep,
        SweepOptions,
    )
    from untaped_github.domain import (  # noqa: PLC0415
        ContentConstraint,
        ContentOptions,
        ContentQuestion,
        PathConstraint,
        PathFilters,
        PathQuestion,
        RefSelector,
        SweepQuery,
        SweepScope,
    )
    from untaped_github.infrastructure import GitCorpusCache  # noqa: PLC0415
    from untaped_github.infrastructure.git_corpus import git_auth_header  # noqa: PLC0415

    with report_errors():
        if refresh and cached:
            raise_usage("--refresh and --cached are mutually exclusive")
        orgs = tuple(org or ())
        teams = tuple(team or ())
        repos = tuple(repo or ())
        if not (orgs or teams or repos or stdin):
            raise_usage("sweep requires --org, --team, --repo, or --stdin")
        if cached and teams:
            raise_usage("--team requires the API and cannot resolve from cached corpus metadata")

        question_label = "REGEX" if question_kind == "content" else "GLOB"
        try:
            question = (
                ContentQuestion(pattern) if question_kind == "content" else PathQuestion(pattern)
            )
        except ValueError as exc:
            raise ConfigError(f"{question_label} {pattern!r}: {exc}") from exc
        normalized_constraint_list: list[ContentConstraint | PathConstraint] = []
        for kind, value in constraints or ():
            try:
                constraint = (
                    ContentConstraint(kind, value)
                    if kind in ("with_content", "without_content")
                    else PathConstraint(cast("Literal['with_path', 'without_path']", kind), value)
                )
            except ValueError as exc:
                label = f"--{kind.replace('_', '-')}"
                raise ConfigError(f"{label} {value!r}: {exc}") from exc
            normalized_constraint_list.append(constraint)
        normalized_constraints = tuple(normalized_constraint_list)
        for label, values, include in (
            ("--include-path", include_path, True),
            ("--exclude-path", exclude_path, False),
        ):
            for value in values or ():
                try:
                    PathFilters(
                        include=(value,) if include else (),
                        exclude=() if include else (value,),
                    )
                except ValueError as exc:
                    raise ConfigError(f"{label} {value!r}: {exc}") from exc
        query = SweepQuery(
            scope=SweepScope(
                orgs=orgs,
                teams=teams,
                repos=repos,
                stdin=stdin,
                include_archived=include_archived,
            ),
            question=question,
            constraints=normalized_constraints,
            content_options=ContentOptions(
                mode="fixed_strings" if fixed_strings else "extended_regex",
                ignore_case=ignore_case,
                word_regexp=word_regexp,
            ),
            path_filters=PathFilters(
                include=tuple(include_path or ()),
                exclude=tuple(exclude_path or ()),
            ),
            refs=RefSelector(profile=refs, globs=tuple(ref or ())),
            freshness="cached" if cached else "refresh" if refresh else "auto",
            context=context,
        )
        settings = app_context().section("github", GithubSettings)
        stdin_repos = tuple(read_identifiers([], stdin=True, id_field="full_name")) if stdin else ()
        corpus = GitCorpusCache()
        options = SweepOptions(
            query=query,
            stdin_repos=tuple(dict.fromkeys(stdin_repos)),
            fetch_depth=settings.sweep.fetch_depth,
            sync_concurrency=_configured_concurrency(settings.sweep.sync_concurrency),
            max_age_seconds=settings.sweep.max_age_seconds,
        )
        if cached:
            report = Sweep(
                inventory=lambda _scope: (),
                corpus=corpus,
                root=settings.corpus_path,
                auth_header=lambda: None,
            )(options)
        else:
            with open_client() as (client, ui):
                token = _token(settings)
                with ui.progress("Sweeping repositories…"):
                    report = Sweep(
                        inventory=ResolveRepositoryInventory(client),
                        corpus=corpus,
                        root=settings.corpus_path,
                        auth_header=lambda: git_auth_header(token) if token else None,
                    )(options)

        emit_sweep_report(report, fmt=fmt, columns=columns)
        _status(report)
        finish(
            (fail_on_match and bool(report.results)) or (require_complete and bool(report.failures))
        )


def _token(settings: GithubSettings) -> str:
    if settings.token is None:
        return ""
    return settings.token.get_secret_value().strip()


def _configured_concurrency(value: int) -> int:
    cap = 32
    if value <= cap:
        return value
    echo(
        f"warning: github.sweep.sync_concurrency {value} clamped to {cap} (Git corpus worker cap)",
        err=True,
    )
    return cap


def _status(report: object) -> None:
    from untaped_github.domain import SweepReport  # noqa: PLC0415

    if not isinstance(report, SweepReport):  # pragma: no cover - defensive type boundary
        raise TypeError("expected SweepReport")
    for failure in report.failures:
        echo(
            f"warning: unscanned {failure.full_name} ({failure.stage}): {failure.reason}",
            err=True,
        )
    summary = report.summary
    oldest = (
        summary.oldest_fetched_at.isoformat() if summary.oldest_fetched_at is not None else "n/a"
    )
    echo(
        (
            f"Sweep: {summary.matched} matched of {summary.scanned} scanned; "
            f"{summary.unscanned} unscanned; {summary.refreshed} refreshed, "
            f"{summary.cached} cached; oldest fetch {oldest}"
        ),
        err=True,
    )


_Hidden = Annotated[bool, Parameter(show=False, negative="")]
_HiddenList = Annotated[
    list[str] | None,
    Parameter(show=False, consume_multiple=False),
]


@app.default
def _migration_command(
    *tokens: str,
    org: Annotated[_HiddenList, Parameter(name="--org")] = None,
    team: Annotated[_HiddenList, Parameter(name="--team")] = None,
    repo: Annotated[_HiddenList, Parameter(name="--repo")] = None,
    stdin: Annotated[_Hidden, Parameter(name="--stdin")] = False,
    grep: Annotated[_HiddenList, Parameter(name="--grep")] = None,
    not_grep: Annotated[_HiddenList, Parameter(name="--not-grep")] = None,
    has_file: Annotated[_HiddenList, Parameter(name="--has-file")] = None,
    lacks_file: Annotated[_HiddenList, Parameter(name="--lacks-file")] = None,
    path: Annotated[_HiddenList, Parameter(name="--path")] = None,
    any_mode: Annotated[_Hidden, Parameter(name="--any")] = False,
    show: Annotated[str | None, Parameter(name="--show", show=False)] = None,
    owners: Annotated[
        bool | None,
        Parameter(name="--owners", negative="--no-owners", show=False),
    ] = None,
    depth: Annotated[str | None, Parameter(name="--depth", show=False)] = None,
    parallel: Annotated[str | None, Parameter(name=["--parallel", "-j"], show=False)] = None,
    ignore_case: Annotated[_Hidden, Parameter(name=["--ignore-case", "-i"])] = False,
    fixed_strings: Annotated[_Hidden, Parameter(name=["--fixed-strings", "-F"])] = False,
    word_regexp: Annotated[_Hidden, Parameter(name=["--word-regexp", "-w"])] = False,
    refs: Annotated[str | None, Parameter(name="--refs", show=False)] = None,
    ref: Annotated[_HiddenList, Parameter(name="--ref")] = None,
    fmt: Annotated[str | None, Parameter(name=["--format", "-f"], show=False)] = None,
    columns: Annotated[_HiddenList, Parameter(name=["--columns", "-c"])] = None,
    fail_on_match: Annotated[_Hidden, Parameter(name="--fail-on-match")] = False,
    strict: Annotated[_Hidden, Parameter(name="--strict")] = False,
    sync: Annotated[_Hidden, Parameter(name="--sync")] = False,
    no_sync: Annotated[_Hidden, Parameter(name="--no-sync")] = False,
    archived: Annotated[_Hidden, Parameter(name="--archived")] = False,
) -> None:
    """Reject the retired flat sweep syntax with replacement guidance."""
    del (
        tokens,
        org,
        team,
        repo,
        stdin,
        ignore_case,
        fixed_strings,
        word_regexp,
        refs,
        ref,
        fmt,
        columns,
        fail_on_match,
    )
    migrations = (
        (bool(grep), "old --grep syntax was removed", "sweep content REGEX"),
        (bool(not_grep), "--not-grep was removed; use --without-content", "sweep content REGEX"),
        (bool(has_file), "old --has-file syntax was removed", "sweep paths GLOB"),
        (bool(lacks_file), "--lacks-file was removed; use --without-path", "sweep paths GLOB"),
        (
            bool(path),
            "--path was removed; use --include-path or --exclude-path",
            "sweep content REGEX",
        ),
        (any_mode, "--any was removed; constraints are always conjunctive", None),
        (
            show is not None,
            "--show was removed; every sweep now emits one complete report",
            None,
        ),
        (
            owners is not None,
            "--owners was removed; primary-evidence owners are always resolved",
            None,
        ),
        (
            depth is not None,
            "--depth was removed; configure github.sweep.fetch_depth",
            None,
        ),
        (
            parallel is not None,
            "--parallel was removed; configure github.sweep.sync_concurrency",
            None,
        ),
        (strict, "--strict was removed; use --require-complete", None),
        (sync, "--sync was removed; use --refresh", None),
        (no_sync, "--no-sync was removed; use --cached", None),
        (archived, "--archived was removed; use --include-archived", None),
    )
    both = "sweep content REGEX or sweep paths GLOB"
    for active, message, target in migrations:
        if active:
            raise_usage(f"{message}; migrate with {target or both}")
    raise_usage(f"old flat sweep syntax was removed; choose {both}")


__all__ = ["app"]
