from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from untaped.api import ConfigError

from untaped_github.application import (
    RepositoryInventoryItem,
    RepositoryInventoryScope,
)
from untaped_github.application.sweep import Sweep, SweepOptions
from untaped_github.domain import (
    ContentConstraint,
    ContentMatch,
    ContentOptions,
    ContentQuestion,
    CorpusFreshness,
    CorpusRepoResult,
    CorpusRepoTarget,
    GrepHit,
    PathConstraint,
    PathFilters,
    PathMatch,
    PathQuestion,
    RefSelector,
    SweepFailure,
    SweepQuery,
    SweepScope,
)
from untaped_github.domain.errors import GitCorpusError

MAIN = "refs/heads/main"
BRANCH = "refs/heads/release/1"
TAG = "refs/tags/release/1"
FETCHED_AT = datetime(2026, 7, 10, 12, tzinfo=UTC)


def _item(full_name: str, *, archived: bool = False) -> RepositoryInventoryItem:
    return RepositoryInventoryItem(
        full_name=full_name,
        name=full_name.rsplit("/", maxsplit=1)[-1],
        html_url=f"https://github.example.com/{full_name}",
        clone_url=f"https://github.example.com/{full_name}.git",
        default_branch="main",
        archived=archived,
    )


def _row(
    full_name: str,
    *,
    archived: bool = False,
    profile: str = "default",
    ref_globs: tuple[str, ...] = (),
    ref: str = "main",
    clone_url: str | None = None,
    fetched_at: str | None = None,
) -> CorpusRepoResult:
    return CorpusRepoResult(
        repo=full_name,
        ref=ref,
        path=f"/corpus/{full_name}",
        clone_url=clone_url or f"https://github.example.com/{full_name}.git",
        fetched_at=fetched_at or FETCHED_AT.isoformat(),
        profile=profile,
        ref_globs=ref_globs,
        archived=archived,
    )


def _query(
    question: ContentQuestion | PathQuestion,
    *,
    constraints: tuple[ContentConstraint | PathConstraint, ...] = (),
    scope: SweepScope | None = None,
    refs: RefSelector | None = None,
    freshness: str = "auto",
    context: int = 0,
    content_options: ContentOptions | None = None,
    path_filters: PathFilters | None = None,
) -> SweepQuery:
    return SweepQuery(
        scope=scope or SweepScope(repos=("acme/api",)),
        question=question,
        constraints=constraints,
        refs=refs or RefSelector(),
        freshness=freshness,  # type: ignore[arg-type]
        context=context,
        content_options=content_options or ContentOptions(),
        path_filters=path_filters or PathFilters(),
    )


def _options(
    query: SweepQuery,
    *,
    stdin_repos: tuple[str, ...] = (),
    fetch_depth: int = 1,
    sync_concurrency: int = 1,
    max_age_seconds: int = 3600,
) -> SweepOptions:
    return SweepOptions(
        query=query,
        stdin_repos=stdin_repos,
        fetch_depth=fetch_depth,
        sync_concurrency=sync_concurrency,
        max_age_seconds=max_age_seconds,
    )


class _Resolver:
    def __init__(self, rows: tuple[RepositoryInventoryItem, ...]) -> None:
        self.rows = rows
        self.scopes: list[RepositoryInventoryScope] = []

    def __call__(self, scope: RepositoryInventoryScope) -> tuple[RepositoryInventoryItem, ...]:
        self.scopes.append(scope)
        return self.rows


@dataclass(frozen=True)
class _SyncCall:
    repo: str
    selector: RefSelector
    depth: int


class _Corpus:
    def __init__(
        self,
        *,
        cached_rows: tuple[CorpusRepoResult, ...] = (),
        freshness: dict[str, CorpusFreshness] | None = None,
        freshness_failures: dict[str, str] | None = None,
        sync_failures: dict[str, str] | None = None,
    ) -> None:
        self.cached_rows = cached_rows
        self.freshness = {
            name: value
            if value.default_branch is not None
            else replace(value, default_branch="main")
            for name, value in (freshness or {}).items()
        }
        self.freshness_failures = freshness_failures or {}
        self.sync_failures = sync_failures or {}
        self.validation_errors: dict[str, str] = {}
        self.synced: list[_SyncCall] = []
        self.local_ref_map: dict[str, tuple[str, ...]] = {}
        self.local_ref_failures: dict[str, str] = {}
        self.tree_map: dict[tuple[str, str], tuple[str, ...]] = {}
        self.grep_map: dict[tuple[str, str, str], tuple[GrepHit, ...]] = {}
        self.blob_map: dict[tuple[str, str, str], str | None] = {}
        self.blob_failures: dict[tuple[str, str, str], str] = {}
        self.grep_calls: list[tuple[str, str, str, bool, bool, bool]] = []
        self.read_calls: list[tuple[str, str, str]] = []

    def sync_repo(
        self,
        repo: CorpusRepoTarget,
        *,
        root: Path,
        selector: RefSelector,
        depth: int,
        auth_header: str | None,
    ) -> CorpusRepoResult:
        self.synced.append(_SyncCall(repo.full_name, selector, depth))
        reason = self.sync_failures.get(repo.full_name)
        if reason is not None:
            raise GitCorpusError(reason)
        self.freshness[repo.full_name] = CorpusFreshness(
            fetched_at=FETCHED_AT,
            profile=selector.profile,
            default_branch=repo.default_branch,
            ref_globs=selector.globs,
            archived=repo.archived,
        )
        return _row(
            repo.full_name,
            archived=repo.archived,
            profile=selector.profile,
            ref_globs=selector.globs,
        )

    def repo_freshness(self, repo: CorpusRepoTarget, *, root: Path) -> CorpusFreshness | None:
        reason = self.freshness_failures.get(repo.full_name)
        if reason is not None:
            raise GitCorpusError(reason)
        return self.freshness.get(repo.full_name)

    def local_refs(
        self,
        repo: CorpusRepoTarget,
        *,
        root: Path,
        selector: RefSelector,
    ) -> tuple[str, ...]:
        reason = self.local_ref_failures.get(repo.full_name)
        if reason is not None:
            raise GitCorpusError(reason)
        return self.local_ref_map.get(repo.full_name, (MAIN,))

    def grep_ref(
        self,
        repo: CorpusRepoTarget,
        *,
        root: Path,
        ref: str,
        pattern: str,
        ignore_case: bool,
        fixed_strings: bool,
        word_regexp: bool,
    ) -> tuple[GrepHit, ...]:
        self.grep_calls.append(
            (repo.full_name, ref, pattern, ignore_case, fixed_strings, word_regexp)
        )
        return self.grep_map.get((repo.full_name, ref, pattern), ())

    def tree_paths(self, repo: CorpusRepoTarget, *, root: Path, ref: str) -> tuple[str, ...]:
        return self.tree_map.get((repo.full_name, ref), ())

    def read_blob(
        self,
        repo: CorpusRepoTarget,
        *,
        root: Path,
        ref: str,
        path: str,
    ) -> str | None:
        self.read_calls.append((repo.full_name, ref, path))
        reason = self.blob_failures.get((repo.full_name, ref, path))
        if reason is not None:
            raise GitCorpusError(reason)
        return self.blob_map.get((repo.full_name, ref, path))

    def validate_pattern(
        self,
        *,
        root: Path,
        pattern: str,
        fixed_strings: bool,
    ) -> str | None:
        return self.validation_errors.get(pattern)

    def list_repos(self, *, root: Path) -> tuple[CorpusRepoResult, ...]:
        return self.cached_rows


def _sweep(corpus: _Corpus, resolver: _Resolver, root: Path) -> Sweep:
    return Sweep(
        inventory=resolver,
        corpus=corpus,
        root=root,
        auth_header=lambda: "AUTHORIZATION: basic token",
    )


def _hit(path: str, *, line: int = 1, text: str = "needle", oid: str = "oid") -> GrepHit:
    return GrepHit(path=path, line=line, text=text, blob_oid=oid)


def test_matchers_compile_before_inventory_or_repository_preparation(tmp_path: Path) -> None:
    corpus = _Corpus()
    corpus.validation_errors["["] = "invalid regular expression"
    resolver = _Resolver((_item("acme/api"),))

    with pytest.raises(ConfigError, match="invalid regular expression"):
        _sweep(corpus, resolver, tmp_path / "corpus")(
            _options(_query(ContentQuestion(pattern="[")))
        )

    assert resolver.scopes == []
    assert corpus.synced == []


@pytest.mark.parametrize("question_kind", ["content", "path"])
@pytest.mark.parametrize(
    "constraint",
    [
        ContentConstraint(kind="with_content", pattern="required"),
        ContentConstraint(kind="without_content", pattern="forbidden"),
        PathConstraint(kind="with_path", pattern="required.txt"),
        PathConstraint(kind="without_path", pattern="forbidden.txt"),
    ],
)
def test_primary_and_each_constraint_must_match_on_the_same_ref(
    tmp_path: Path,
    question_kind: str,
    constraint: ContentConstraint | PathConstraint,
) -> None:
    corpus = _Corpus()
    corpus.local_ref_map["acme/api"] = (MAIN, BRANCH)
    if question_kind == "content":
        question = ContentQuestion(pattern="primary")
        corpus.grep_map[("acme/api", MAIN, "primary")] = (_hit("primary.txt"),)
    else:
        question = PathQuestion(pattern="primary.txt")
        corpus.tree_map[("acme/api", MAIN)] = ("primary.txt",)

    if constraint.kind == "with_content":
        corpus.grep_map[("acme/api", BRANCH, constraint.pattern)] = (_hit("witness.txt"),)
    elif constraint.kind == "without_content":
        corpus.grep_map[("acme/api", MAIN, constraint.pattern)] = (_hit("witness.txt"),)
    elif constraint.kind == "with_path":
        corpus.tree_map[("acme/api", BRANCH)] = ("required.txt",)
    else:
        current = corpus.tree_map.get(("acme/api", MAIN), ())
        corpus.tree_map[("acme/api", MAIN)] = (*current, "forbidden.txt")

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(_query(question, constraints=(constraint,)))
    )

    assert report.results == ()
    assert report.summary.scanned == 1
    assert report.summary.matched == 0


def test_constraints_are_conjunctive_and_only_primary_content_is_reported(tmp_path: Path) -> None:
    corpus = _Corpus()
    corpus.grep_map[("acme/api", MAIN, "primary")] = (_hit("src/app.py", text="primary"),)
    corpus.grep_map[("acme/api", MAIN, "required")] = (
        _hit("constraint-only.txt", text="required", oid="constraint"),
    )
    corpus.tree_map[("acme/api", MAIN)] = ("src/app.py", "required.txt")

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(
            _query(
                ContentQuestion(pattern="primary"),
                constraints=(
                    ContentConstraint(kind="with_content", pattern="required"),
                    ContentConstraint(kind="without_content", pattern="forbidden"),
                    PathConstraint(kind="with_path", pattern="required.txt"),
                    PathConstraint(kind="without_path", pattern="forbidden.txt"),
                ),
            )
        )
    )

    assert report.results[0].refs_matched == (MAIN,)
    assert report.results[0].matches == (
        ContentMatch(refs=(MAIN,), path="src/app.py", start_line=1, end_line=1, content="primary"),
    )


def test_content_filters_and_modifiers_apply_to_primary_and_constraints(tmp_path: Path) -> None:
    corpus = _Corpus()
    for pattern in ("primary", "required"):
        corpus.grep_map[("acme/api", MAIN, pattern)] = (
            _hit("README.md", text=pattern, oid=f"{pattern}-readme"),
            _hit("src/app.py", text=pattern, oid=f"{pattern}-app"),
            _hit("src/vendor/app.py", text=pattern, oid=f"{pattern}-vendor"),
        )

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(
            _query(
                ContentQuestion(pattern="primary"),
                constraints=(ContentConstraint(kind="with_content", pattern="required"),),
                content_options=ContentOptions(
                    mode="fixed_strings", ignore_case=True, word_regexp=True
                ),
                path_filters=PathFilters(include=("src/**",), exclude=("src/vendor/**",)),
            )
        )
    )

    assert [match.path for match in report.results[0].matches] == ["src/app.py"]
    assert corpus.grep_calls == [
        ("acme/api", MAIN, "primary", True, True, True),
        ("acme/api", MAIN, "required", True, True, True),
    ]


def test_content_grouping_keeps_distinct_content_and_canonical_ref_collisions(
    tmp_path: Path,
) -> None:
    corpus = _Corpus()
    corpus.local_ref_map["acme/api"] = (MAIN, BRANCH, TAG)
    corpus.grep_map[("acme/api", MAIN, "needle")] = (
        _hit("app.py", line=3, text="same", oid="same-oid"),
    )
    corpus.grep_map[("acme/api", BRANCH, "needle")] = (
        _hit("app.py", line=3, text="same", oid="same-oid"),
    )
    corpus.grep_map[("acme/api", TAG, "needle")] = (
        _hit("app.py", line=3, text="different", oid="tag-oid"),
    )

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(_query(ContentQuestion(pattern="needle"), refs=RefSelector(profile="all")))
    )

    assert report.results[0].refs_matched == (MAIN, BRANCH, TAG)
    assert report.results[0].matches == (
        ContentMatch(refs=(TAG,), path="app.py", start_line=3, end_line=3, content="different"),
        ContentMatch(refs=(MAIN, BRANCH), path="app.py", start_line=3, end_line=3, content="same"),
    )


def test_content_grouping_keeps_identical_visible_hits_separate_when_blob_oids_differ(
    tmp_path: Path,
) -> None:
    corpus = _Corpus()
    corpus.local_ref_map["acme/api"] = (BRANCH, TAG)
    corpus.grep_map[("acme/api", BRANCH, "needle")] = (
        _hit("app.py", line=3, text="same", oid="branch-oid"),
    )
    corpus.grep_map[("acme/api", TAG, "needle")] = (
        _hit("app.py", line=3, text="same", oid="tag-oid"),
    )

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(_query(ContentQuestion(pattern="needle"), refs=RefSelector(profile="all")))
    )

    assert report.results[0].matches == (
        ContentMatch(refs=(BRANCH,), path="app.py", start_line=3, end_line=3, content="same"),
        ContentMatch(refs=(TAG,), path="app.py", start_line=3, end_line=3, content="same"),
    )


def test_path_evidence_groups_only_by_path_across_canonical_refs(tmp_path: Path) -> None:
    corpus = _Corpus()
    corpus.local_ref_map["acme/api"] = (BRANCH, TAG)
    corpus.tree_map[("acme/api", BRANCH)] = ("Jenkinsfile",)
    corpus.tree_map[("acme/api", TAG)] = ("Jenkinsfile",)

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(_query(PathQuestion(pattern="Jenkinsfile"), refs=RefSelector(profile="all")))
    )

    assert report.results[0].matches == (PathMatch(refs=(BRANCH, TAG), path="Jenkinsfile"),)


def test_context_clips_boundaries_and_reads_each_primary_blob_once(tmp_path: Path) -> None:
    corpus = _Corpus()
    corpus.grep_map[("acme/api", MAIN, "needle")] = (
        _hit("app.py", line=1, text="one", oid="shared"),
        _hit("app.py", line=4, text="four", oid="shared"),
    )
    corpus.blob_map[("acme/api", MAIN, "app.py")] = "one\ntwo\nthree\nfour\nfive"

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(_query(ContentQuestion(pattern="needle"), context=2))
    )

    first, second = report.results[0].matches
    assert isinstance(first, ContentMatch)
    assert first.context is not None
    assert first.context.to_dict() == {"start_line": 1, "end_line": 3, "content": "one\ntwo\nthree"}
    assert isinstance(second, ContentMatch)
    assert second.context is not None
    assert second.context.to_dict() == {
        "start_line": 2,
        "end_line": 5,
        "content": "two\nthree\nfour\nfive",
    }
    assert corpus.read_calls.count(("acme/api", MAIN, "app.py")) == 1


def test_context_is_read_only_after_the_ref_qualifies(tmp_path: Path) -> None:
    corpus = _Corpus()
    corpus.local_ref_map["acme/api"] = (MAIN, BRANCH)
    corpus.grep_map[("acme/api", MAIN, "primary")] = (
        _hit("rejected.py", text="primary", oid="rejected"),
    )
    corpus.grep_map[("acme/api", BRANCH, "primary")] = (
        _hit("accepted.py", text="primary", oid="accepted"),
    )
    corpus.grep_map[("acme/api", MAIN, "forbidden")] = (
        _hit("witness.py", text="forbidden", oid="witness"),
    )
    corpus.blob_map[("acme/api", BRANCH, "accepted.py")] = "before\nprimary\nafter"

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(
            _query(
                ContentQuestion(pattern="primary"),
                constraints=(ContentConstraint(kind="without_content", pattern="forbidden"),),
                context=1,
            )
        )
    )

    assert report.results[0].refs_matched == (BRANCH,)
    assert ("acme/api", MAIN, "rejected.py") not in corpus.read_calls
    assert corpus.read_calls.count(("acme/api", BRANCH, "accepted.py")) == 1


def test_codeowners_are_resolved_per_qualifying_ref_from_primary_paths_only(
    tmp_path: Path,
) -> None:
    corpus = _Corpus()
    corpus.local_ref_map["acme/api"] = (MAIN, TAG)
    for ref in (MAIN, TAG):
        corpus.grep_map[("acme/api", ref, "primary")] = (
            _hit("src/app.py", text="primary", oid=f"primary-{ref}"),
        )
        corpus.grep_map[("acme/api", ref, "required")] = (
            _hit("constraint/witness.py", text="required", oid=f"constraint-{ref}"),
        )
    corpus.blob_map[("acme/api", MAIN, ".github/CODEOWNERS")] = (
        "src/ @main-primary\nconstraint/ @constraint-owner\n"
    )
    corpus.blob_map[("acme/api", TAG, ".github/CODEOWNERS")] = (
        "src/ @tag-primary\nconstraint/ @constraint-owner\n"
    )

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(
            _query(
                ContentQuestion(pattern="primary"),
                constraints=(ContentConstraint(kind="with_content", pattern="required"),),
                refs=RefSelector(profile="all"),
            )
        )
    )

    assert report.results[0].owners == ("@main-primary", "@tag-primary")
    assert "@constraint-owner" not in report.results[0].owners
    assert ("acme/api", MAIN, ".github/CODEOWNERS") in corpus.read_calls
    assert ("acme/api", TAG, ".github/CODEOWNERS") in corpus.read_calls


def test_missing_codeowners_is_not_a_scan_failure(tmp_path: Path) -> None:
    corpus = _Corpus()
    corpus.tree_map[("acme/api", MAIN)] = ("README.md",)

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(_query(PathQuestion(pattern="README.md")))
    )

    assert report.results[0].owners == ()
    assert report.failures == ()


def test_operational_codeowners_read_failure_is_a_scan_failure(tmp_path: Path) -> None:
    corpus = _Corpus()
    corpus.tree_map[("acme/api", MAIN)] = ("README.md",)
    corpus.blob_failures[("acme/api", MAIN, ".github/CODEOWNERS")] = "git show failed"

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(_query(PathQuestion(pattern="README.md")))
    )

    assert report.results == ()
    assert report.failures == (SweepFailure("acme/api", "scan", "git show failed"),)


def test_codeowners_parse_failure_is_a_scan_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = _Corpus()
    corpus.tree_map[("acme/api", MAIN)] = ("README.md",)
    corpus.blob_map[("acme/api", MAIN, ".github/CODEOWNERS")] = "* @acme/platform\n"

    def fail_parse(_text: str) -> None:
        raise ValueError("parser exploded")

    monkeypatch.setattr("untaped_github.application.sweep.parse_codeowners", fail_parse)

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(_query(PathQuestion(pattern="README.md")))
    )

    assert report.results == ()
    assert report.failures == (
        SweepFailure(
            "acme/api",
            "scan",
            "could not parse CODEOWNERS refs/heads/main:.github/CODEOWNERS: parser exploded",
        ),
    )


def test_prepare_scan_failures_cache_fallback_and_summary_invariants(tmp_path: Path) -> None:
    stale = FETCHED_AT - timedelta(hours=2)
    corpus = _Corpus(
        freshness={
            "acme/fallback": CorpusFreshness(fetched_at=stale, profile="default"),
        },
        sync_failures={
            "acme/fallback": "fallback fetch failed",
            "acme/prepare": "initial fetch failed",
        },
    )
    corpus.local_ref_failures["acme/scan"] = "corrupt ref store"
    corpus.tree_map[("acme/matched", MAIN)] = ("README.md",)
    corpus.tree_map[("acme/fallback", MAIN)] = ()
    resolver = _Resolver(
        tuple(
            _item(name) for name in ("acme/scan", "acme/matched", "acme/prepare", "acme/fallback")
        )
    )

    report = _sweep(corpus, resolver, tmp_path / "corpus")(
        _options(
            _query(
                PathQuestion(pattern="README.md"),
                scope=SweepScope(orgs=("acme",)),
                freshness="refresh",
            )
        )
    )

    assert [result.full_name for result in report.results] == ["acme/matched"]
    assert [(failure.full_name, failure.stage) for failure in report.failures] == [
        ("acme/prepare", "prepare"),
        ("acme/scan", "scan"),
    ]
    assert report.summary.to_dict() == {
        "selected": 4,
        "prepared": 3,
        "scanned": 2,
        "matched": 1,
        "unscanned": 2,
        "refreshed": 2,
        "cached": 1,
        "oldest_fetched_at": stale.isoformat(),
    }


def test_freshness_failure_is_isolated_as_a_prepare_failure(tmp_path: Path) -> None:
    corpus = _Corpus(freshness_failures={"acme/broken": "metadata unreadable"})
    corpus.tree_map[("acme/good", MAIN)] = ("README.md",)
    resolver = _Resolver((_item("acme/broken"), _item("acme/good")))

    report = _sweep(corpus, resolver, tmp_path / "corpus")(
        _options(
            _query(
                PathQuestion(pattern="README.md"),
                scope=SweepScope(orgs=("acme",)),
            )
        )
    )

    assert [result.full_name for result in report.results] == ["acme/good"]
    assert report.failures == (
        SweepFailure(full_name="acme/broken", stage="prepare", reason="metadata unreadable"),
    )
    assert report.summary.to_dict() == {
        "selected": 2,
        "prepared": 1,
        "scanned": 1,
        "matched": 1,
        "unscanned": 1,
        "refreshed": 1,
        "cached": 0,
        "oldest_fetched_at": FETCHED_AT.isoformat(),
    }


def test_auth_header_failures_remain_global(tmp_path: Path) -> None:
    corpus = _Corpus()

    def failing_auth_header() -> str | None:
        raise GitCorpusError("authentication unavailable")

    sweep = Sweep(
        inventory=_Resolver((_item("acme/api"),)),
        corpus=corpus,
        root=tmp_path / "corpus",
        auth_header=failing_auth_header,
    )

    with pytest.raises(GitCorpusError, match="authentication unavailable"):
        sweep(_options(_query(PathQuestion(pattern="README.md"))))


def test_cached_scope_requires_covering_metadata_without_network_calls(tmp_path: Path) -> None:
    corpus = _Corpus(
        cached_rows=(
            _row("acme/covered", profile="all"),
            _row("acme/under", profile="default"),
        ),
        freshness={
            "acme/covered": CorpusFreshness(fetched_at=FETCHED_AT, profile="all"),
            "acme/under": CorpusFreshness(fetched_at=FETCHED_AT, profile="default"),
        },
    )
    corpus.tree_map[("acme/covered", MAIN)] = ("README.md",)
    resolver = _Resolver(())

    report = _sweep(corpus, resolver, tmp_path / "corpus")(
        _options(
            _query(
                PathQuestion(pattern="README.md"),
                scope=SweepScope(orgs=("acme",)),
                refs=RefSelector(profile="branches"),
                freshness="cached",
            )
        )
    )

    assert [result.full_name for result in report.results] == ["acme/covered"]
    assert [(failure.full_name, failure.stage) for failure in report.failures] == [
        ("acme/under", "prepare")
    ]
    assert resolver.scopes == []
    assert corpus.synced == []


def test_cached_scope_rejects_metadata_for_a_different_default_branch(tmp_path: Path) -> None:
    corpus = _Corpus(
        cached_rows=(_row("acme/api", ref="main"),),
        freshness={
            "acme/api": CorpusFreshness(
                fetched_at=FETCHED_AT,
                profile="default",
                default_branch="master",
            )
        },
    )

    report = _sweep(corpus, _Resolver(()), tmp_path / "corpus")(
        _options(
            _query(
                PathQuestion(pattern="README.md"),
                scope=SweepScope(repos=("acme/api",)),
                freshness="cached",
            )
        )
    )

    assert report.results == ()
    assert report.failures == (
        SweepFailure("acme/api", "prepare", "cached corpus does not cover the selected refs"),
    )
    assert corpus.synced == []


def test_auto_refreshes_cache_when_inventory_default_branch_changed(tmp_path: Path) -> None:
    corpus = _Corpus(
        freshness={
            "acme/api": CorpusFreshness(
                fetched_at=datetime.now(UTC),
                profile="default",
                default_branch="master",
            )
        }
    )
    corpus.tree_map[("acme/api", MAIN)] = ("README.md",)

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(_query(PathQuestion(pattern="README.md")))
    )

    assert report.failures == ()
    assert report.summary.refreshed == 1
    assert [call.repo for call in corpus.synced] == ["acme/api"]


def test_failed_drift_refresh_does_not_fall_back_to_mismatched_branch(tmp_path: Path) -> None:
    corpus = _Corpus(
        freshness={
            "acme/api": CorpusFreshness(
                fetched_at=FETCHED_AT,
                profile="default",
                default_branch="master",
            )
        },
        sync_failures={"acme/api": "fetch failed"},
    )

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(_query(PathQuestion(pattern="README.md")))
    )

    assert report.results == ()
    assert report.failures == (SweepFailure("acme/api", "prepare", "fetch failed"),)
    assert report.summary.prepared == 0


def test_cached_scope_is_additive_and_missing_explicit_repos_are_prepare_failures(
    tmp_path: Path,
) -> None:
    names = ("acme/from-org", "other/explicit", "other/unselected")
    corpus = _Corpus(
        cached_rows=tuple(_row(name, profile="all") for name in names),
        freshness={name: CorpusFreshness(fetched_at=FETCHED_AT, profile="all") for name in names},
    )
    corpus.tree_map[("acme/from-org", MAIN)] = ("README.md",)
    corpus.tree_map[("other/explicit", MAIN)] = ("README.md",)

    report = _sweep(corpus, _Resolver(()), tmp_path / "corpus")(
        _options(
            _query(
                PathQuestion(pattern="README.md"),
                scope=SweepScope(orgs=("acme",), repos=("other/explicit", "other/missing")),
                freshness="cached",
            )
        )
    )

    assert [result.full_name for result in report.results] == [
        "acme/from-org",
        "other/explicit",
    ]
    assert [(failure.full_name, failure.stage) for failure in report.failures] == [
        ("other/missing", "prepare")
    ]
    assert report.summary.selected == 3


def test_cached_scope_dedupes_metadata_and_prefers_newest_valid_row(tmp_path: Path) -> None:
    older = (FETCHED_AT - timedelta(hours=1)).isoformat()
    newer = FETCHED_AT.isoformat()
    corpus = _Corpus(
        cached_rows=(
            _row(
                "acme/api",
                ref="old",
                clone_url="https://github.example.com/acme/old.git",
                fetched_at=older,
            ),
            _row(
                "acme/api",
                ref="main",
                clone_url="https://github.example.com/acme/new.git",
                fetched_at=newer,
            ),
            _row("acme/api", ref="invalid", fetched_at="not-a-timestamp"),
        ),
        freshness={"acme/api": CorpusFreshness(fetched_at=FETCHED_AT, profile="default")},
    )
    corpus.tree_map[("acme/api", MAIN)] = ("README.md",)

    report = _sweep(corpus, _Resolver(()), tmp_path / "corpus")(
        _options(
            _query(
                PathQuestion(pattern="README.md"),
                scope=SweepScope(orgs=("acme",), repos=("acme/api", "acme/missing")),
                freshness="cached",
            )
        )
    )

    assert [result.full_name for result in report.results] == ["acme/api"]
    assert report.results[0].clone_url == "https://github.example.com/acme/new.git"
    assert report.failures == (
        SweepFailure("acme/missing", "prepare", "cached corpus does not cover the selected refs"),
    )
    assert report.summary.selected == 2


def test_cached_team_scope_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="--team requires the API"):
        _sweep(_Corpus(), _Resolver(()), tmp_path / "corpus")(
            _options(
                _query(
                    PathQuestion(pattern="README.md"),
                    scope=SweepScope(teams=("acme/platform",)),
                    freshness="cached",
                )
            )
        )


def test_operational_config_values_drive_refresh_depth_age_and_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from untaped_github.application import sweep as sweep_module

    observed_concurrency: list[int] = []

    def recording_map(
        function: object,
        items: object,
        *,
        concurrency: int,
        on_each: object,
    ) -> None:
        observed_concurrency.append(concurrency)
        for item in items:  # type: ignore[union-attr]
            on_each(item, function(item))  # type: ignore[operator]

    monkeypatch.setattr(sweep_module, "bounded_map", recording_map)
    corpus = _Corpus(
        freshness={
            "acme/api": CorpusFreshness(
                fetched_at=datetime.now(UTC) - timedelta(seconds=10), profile="default"
            )
        }
    )
    corpus.tree_map[("acme/api", MAIN)] = ("README.md",)

    report = _sweep(corpus, _Resolver((_item("acme/api"),)), tmp_path / "corpus")(
        _options(
            _query(PathQuestion(pattern="README.md")),
            fetch_depth=0,
            sync_concurrency=7,
            max_age_seconds=5,
        )
    )

    assert report.summary.refreshed == 1
    assert corpus.synced[0].depth == 0
    assert observed_concurrency == [7, 7]
