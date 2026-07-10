"""Application use case for evidence-first repository sweep queries."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from untaped.api import ConfigError, bounded_map

from untaped_github.application.inventory import (
    RepositoryInventoryItem,
    RepositoryInventoryScope,
)
from untaped_github.application.ports import GitCorpus
from untaped_github.application.scopes import normalize_team_scopes
from untaped_github.application.sweep_matching import SweepMatchers, compile_sweep_matchers
from untaped_github.domain import (
    CODEOWNERS_LOCATIONS,
    ContentConstraint,
    ContentMatch,
    ContentQuestion,
    CorpusFreshness,
    CorpusRepoTarget,
    GrepHit,
    MatchContext,
    PathMatch,
    RefEvaluation,
    RefSelector,
    SweepFailure,
    SweepMatch,
    SweepQuery,
    SweepReport,
    SweepResult,
    SweepSummary,
    covers,
    parse_codeowners,
    ref_matches,
)
from untaped_github.domain.errors import GitCorpusError

InventoryResolver = Callable[[RepositoryInventoryScope], tuple[RepositoryInventoryItem, ...]]
AuthHeaderSupplier = Callable[[], str | None]


@dataclass(frozen=True)
class SweepOptions:
    """A sweep query plus configuration-only corpus tuning."""

    query: SweepQuery
    stdin_repos: tuple[str, ...] = ()
    fetch_depth: int = 1
    sync_concurrency: int = 12
    max_age_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.fetch_depth < 0:
            raise ValueError("fetch_depth must be non-negative")
        if self.sync_concurrency < 1:
            raise ValueError("sync_concurrency must be positive")
        if self.max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative")


@dataclass(frozen=True)
class _ReadyRepo:
    repo: CorpusRepoTarget
    fetched_at: datetime
    refreshed: bool


@dataclass(frozen=True)
class _RepoScan:
    result: SweepResult | None


@dataclass(frozen=True)
class _ContentEvidence:
    ref: str
    blob_oid: str
    path: str
    start_line: int
    end_line: int
    content: str
    context: MatchContext | None


@dataclass(frozen=True)
class _PathEvidence:
    ref: str
    path: str


type _Evidence = _ContentEvidence | _PathEvidence


@dataclass(frozen=True)
class _RefScan:
    evaluation: RefEvaluation
    evidence: tuple[_Evidence, ...]


class Sweep:
    """Run one primary sweep question across selected repositories and refs."""

    def __init__(
        self,
        *,
        inventory: InventoryResolver,
        corpus: GitCorpus,
        root: Path,
        auth_header: AuthHeaderSupplier,
    ) -> None:
        self._inventory = inventory
        self._corpus = corpus
        self._root = root
        self._auth_header = auth_header

    def __call__(self, options: SweepOptions) -> SweepReport:
        matchers = compile_sweep_matchers(
            options.query,
            corpus=self._corpus,
            root=self._root,
        )
        repos = self._resolve_scope(options)
        ready, prepare_failures = self._prepare_repos(repos, options)
        scans: list[_RepoScan] = []
        scan_failures: list[SweepFailure] = []

        def scan_one(ready_repo: _ReadyRepo) -> _RepoScan | SweepFailure:
            try:
                return self._scan_repo(ready_repo, options.query, matchers)
            except GitCorpusError as exc:
                return SweepFailure(
                    full_name=ready_repo.repo.full_name,
                    stage="scan",
                    reason=str(exc),
                )

        def record(_ready_repo: _ReadyRepo, outcome: _RepoScan | SweepFailure) -> None:
            if isinstance(outcome, SweepFailure):
                scan_failures.append(outcome)
            else:
                scans.append(outcome)

        bounded_map(
            scan_one,
            ready,
            concurrency=options.sync_concurrency,
            on_each=record,
        )
        results = tuple(scan.result for scan in scans if scan.result is not None)
        failures = (*prepare_failures, *scan_failures)
        refreshed = sum(item.refreshed for item in ready)
        return SweepReport(
            query=options.query,
            results=results,
            failures=failures,
            summary=SweepSummary(
                selected=len(repos),
                prepared=len(ready),
                scanned=len(scans),
                matched=len(results),
                unscanned=len(failures),
                refreshed=refreshed,
                cached=len(ready) - refreshed,
                oldest_fetched_at=min((item.fetched_at for item in ready), default=None),
            ),
        )

    def _resolve_scope(self, options: SweepOptions) -> tuple[CorpusRepoTarget, ...]:
        if options.query.freshness == "cached":
            return self._resolve_cached_scope(options)

        try:
            teams = normalize_team_scopes(
                options.query.scope.teams,
                orgs=options.query.scope.orgs,
            )
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        repos = tuple(dict.fromkeys((*options.query.scope.repos, *options.stdin_repos)))
        scope = RepositoryInventoryScope(
            orgs=options.query.scope.orgs,
            teams=teams,
            repos=repos,
        )
        rows = (
            item
            for item in self._inventory(scope)
            if options.query.scope.include_archived or not item.archived
        )
        return tuple(_target(item) for item in rows)

    def _resolve_cached_scope(self, options: SweepOptions) -> tuple[CorpusRepoTarget, ...]:
        scope = options.query.scope
        if scope.teams:
            raise ConfigError(
                "--team requires the API and cannot resolve from cached corpus metadata"
            )
        names = set((*scope.repos, *options.stdin_repos))
        targets: list[CorpusRepoTarget] = []
        rows = self._corpus.list_repos(root=self._root)
        known_names = {row.repo for row in rows}
        for row in rows:
            if not scope.include_archived and row.archived:
                continue
            selected_by_org = any(row.repo.startswith(f"{org}/") for org in scope.orgs)
            if (scope.orgs or names) and not (selected_by_org or row.repo in names):
                continue
            targets.append(
                CorpusRepoTarget(
                    full_name=row.repo,
                    default_branch=row.ref,
                    clone_url=row.clone_url,
                    archived=row.archived,
                )
            )
        targets.extend(
            CorpusRepoTarget(full_name=name, default_branch=None)
            for name in dict.fromkeys((*scope.repos, *options.stdin_repos))
            if name not in known_names
        )
        return tuple(sorted(targets, key=lambda repo: repo.full_name))

    def _prepare_repos(
        self,
        repos: tuple[CorpusRepoTarget, ...],
        options: SweepOptions,
    ) -> tuple[tuple[_ReadyRepo, ...], tuple[SweepFailure, ...]]:
        ready: list[_ReadyRepo] = []
        failures: list[SweepFailure] = []

        def prepare_one(repo: CorpusRepoTarget) -> _ReadyRepo | SweepFailure:
            try:
                freshness = self._corpus.repo_freshness(repo, root=self._root)
            except GitCorpusError as exc:
                return SweepFailure(
                    full_name=repo.full_name,
                    stage="prepare",
                    reason=str(exc),
                )
            if options.query.freshness == "cached":
                if freshness is None or not covers(freshness, options.query.refs):
                    return SweepFailure(
                        full_name=repo.full_name,
                        stage="prepare",
                        reason="cached corpus does not cover the selected refs",
                    )
                return _ReadyRepo(repo=repo, fetched_at=freshness.fetched_at, refreshed=False)

            must_refresh = options.query.freshness == "refresh" or _needs_refresh(
                freshness,
                selector=options.query.refs,
                max_age_seconds=options.max_age_seconds,
            )
            if not must_refresh:
                if freshness is None:  # pragma: no cover - guarded by _needs_refresh
                    raise AssertionError("fresh corpus metadata is required")
                return _ReadyRepo(repo=repo, fetched_at=freshness.fetched_at, refreshed=False)
            auth_header = self._auth_header()
            try:
                result = self._corpus.sync_repo(
                    repo,
                    root=self._root,
                    selector=options.query.refs,
                    depth=options.fetch_depth,
                    auth_header=auth_header,
                )
            except GitCorpusError as exc:
                if freshness is not None and covers(freshness, options.query.refs):
                    return _ReadyRepo(
                        repo=repo,
                        fetched_at=freshness.fetched_at,
                        refreshed=False,
                    )
                return SweepFailure(
                    full_name=repo.full_name,
                    stage="prepare",
                    reason=str(exc),
                )
            fetched_at = _parse_datetime(result.fetched_at)
            if fetched_at is None:
                return SweepFailure(
                    full_name=repo.full_name,
                    stage="prepare",
                    reason="corpus preparation did not record a fetch timestamp",
                )
            return _ReadyRepo(repo=repo, fetched_at=fetched_at, refreshed=True)

        def record(_repo: CorpusRepoTarget, outcome: _ReadyRepo | SweepFailure) -> None:
            if isinstance(outcome, SweepFailure):
                failures.append(outcome)
            else:
                ready.append(outcome)

        bounded_map(
            prepare_one,
            repos,
            concurrency=options.sync_concurrency,
            on_each=record,
        )
        return tuple(ready), tuple(failures)

    def _scan_repo(
        self,
        ready: _ReadyRepo,
        query: SweepQuery,
        matchers: SweepMatchers,
    ) -> _RepoScan:
        qualifying_refs: list[str] = []
        evidence: list[_Evidence] = []
        owners: set[str] = set()
        blob_cache: dict[str, str] = {}
        for ref in self._corpus.local_refs(ready.repo, root=self._root, selector=query.refs):
            ref_scan = self._scan_ref(
                ready.repo,
                ref,
                query,
                matchers,
            )
            if not ref_matches(query, ref_scan.evaluation):
                continue
            qualified_evidence = self._add_context(
                ready.repo,
                ref_scan.evidence,
                radius=query.context,
                blob_cache=blob_cache,
            )
            qualifying_refs.append(ref)
            evidence.extend(qualified_evidence)
            owners.update(
                self._owners_for(
                    ready.repo,
                    ref=ref,
                    paths=(item.path for item in qualified_evidence),
                )
            )

        if not qualifying_refs:
            return _RepoScan(result=None)
        return _RepoScan(
            result=SweepResult(
                full_name=ready.repo.full_name,
                clone_url=ready.repo.clone_url,
                refs_matched=tuple(qualifying_refs),
                matches=_group_evidence(evidence),
                owners=tuple(owners),
                synced_at=ready.fetched_at,
            )
        )

    def _scan_ref(
        self,
        repo: CorpusRepoTarget,
        ref: str,
        query: SweepQuery,
        matchers: SweepMatchers,
    ) -> _RefScan:
        tree: tuple[str, ...] | None = None

        def paths() -> tuple[str, ...]:
            nonlocal tree
            if tree is None:
                tree = self._corpus.tree_paths(repo, root=self._root, ref=ref)
            return tree

        evidence: tuple[_Evidence, ...]
        if isinstance(query.question, ContentQuestion):
            primary_hits = self._grep(repo, ref, query.question.pattern, query, matchers)
            primary_count = len(primary_hits)
            evidence = tuple(
                _ContentEvidence(
                    ref=ref,
                    blob_oid=hit.blob_oid,
                    path=hit.path,
                    start_line=hit.line,
                    end_line=hit.line,
                    content=hit.text,
                    context=None,
                )
                for hit in primary_hits
            )
        else:
            primary_paths = matchers.matching_question_paths(paths())
            primary_count = len(primary_paths)
            evidence = tuple(_PathEvidence(ref=ref, path=path) for path in primary_paths)

        constraint_hits: list[int] = []
        for index, constraint in enumerate(query.constraints):
            if isinstance(constraint, ContentConstraint):
                count = len(self._grep(repo, ref, constraint.pattern, query, matchers))
            else:
                count = len(matchers.matching_constraint_paths(index, paths()))
            constraint_hits.append(count)
        return _RefScan(
            evaluation=RefEvaluation(
                ref=ref,
                question_hits=primary_count,
                constraint_hits=tuple(constraint_hits),
            ),
            evidence=evidence,
        )

    def _grep(
        self,
        repo: CorpusRepoTarget,
        ref: str,
        pattern: str,
        query: SweepQuery,
        matchers: SweepMatchers,
    ) -> tuple[GrepHit, ...]:
        hits = self._corpus.grep_ref(
            repo,
            root=self._root,
            ref=ref,
            pattern=pattern,
            ignore_case=query.content_options.ignore_case,
            fixed_strings=query.content_options.mode == "fixed_strings",
            word_regexp=query.content_options.word_regexp,
        )
        return matchers.filter_content_hits(hits)

    def _add_context(
        self,
        repo: CorpusRepoTarget,
        evidence: tuple[_Evidence, ...],
        *,
        radius: int,
        blob_cache: dict[str, str],
    ) -> tuple[_Evidence, ...]:
        if radius == 0:
            return evidence
        with_context: list[_Evidence] = []
        for item in evidence:
            if isinstance(item, _PathEvidence):
                with_context.append(item)
                continue
            blob = blob_cache.get(item.blob_oid)
            if blob is None:
                blob = self._corpus.read_blob(
                    repo,
                    root=self._root,
                    ref=item.ref,
                    path=item.path,
                )
                if blob is None:
                    raise GitCorpusError(
                        f"matched blob is unavailable for context: {item.ref}:{item.path}"
                    )
                blob_cache[item.blob_oid] = blob
            with_context.append(
                _ContentEvidence(
                    ref=item.ref,
                    blob_oid=item.blob_oid,
                    path=item.path,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    content=item.content,
                    context=_match_context(blob, line=item.start_line, radius=radius),
                )
            )
        return tuple(with_context)

    def _owners_for(
        self,
        repo: CorpusRepoTarget,
        *,
        ref: str,
        paths: Iterable[str],
    ) -> tuple[str, ...]:
        rules = None
        for codeowners_path in CODEOWNERS_LOCATIONS:
            try:
                text = self._corpus.read_blob(
                    repo,
                    root=self._root,
                    ref=ref,
                    path=codeowners_path,
                )
            except GitCorpusError:
                return ()
            if text is None:
                continue
            try:
                rules = parse_codeowners(text)
            except Exception:
                return ()
            break
        if rules is None:
            return ()
        return tuple(owner for path in sorted(set(paths)) for owner in rules.owners_for(path))


def _target(item: RepositoryInventoryItem) -> CorpusRepoTarget:
    return CorpusRepoTarget(
        full_name=item.full_name,
        default_branch=item.default_branch,
        clone_url=item.clone_url,
        html_url=item.html_url,
        archived=item.archived,
    )


def _needs_refresh(
    freshness: CorpusFreshness | None,
    *,
    selector: RefSelector,
    max_age_seconds: int,
) -> bool:
    if freshness is None or not covers(freshness, selector):
        return True
    return (datetime.now(UTC) - freshness.fetched_at).total_seconds() > max_age_seconds


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _match_context(blob: str, *, line: int, radius: int) -> MatchContext:
    lines = blob.splitlines()
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    return MatchContext(
        start_line=start,
        end_line=end,
        content="\n".join(lines[start - 1 : end]),
    )


def _group_evidence(evidence: Iterable[_Evidence]) -> tuple[SweepMatch, ...]:
    content_groups: dict[
        tuple[str, str, int, int, str],
        tuple[list[str], MatchContext | None],
    ] = {}
    path_groups: dict[str, list[str]] = {}
    for item in evidence:
        if isinstance(item, _ContentEvidence):
            key = (
                item.blob_oid,
                item.path,
                item.start_line,
                item.end_line,
                item.content,
            )
            refs, _context = content_groups.setdefault(key, ([], item.context))
            refs.append(item.ref)
        else:
            path_groups.setdefault(item.path, []).append(item.ref)
    matches: list[SweepMatch] = [
        ContentMatch(
            refs=tuple(refs),
            path=path,
            start_line=start_line,
            end_line=end_line,
            content=content,
            context=context,
        )
        for (_blob_oid, path, start_line, end_line, content), (
            refs,
            context,
        ) in content_groups.items()
    ]
    matches.extend(PathMatch(refs=tuple(refs), path=path) for path, refs in path_groups.items())
    return tuple(matches)
