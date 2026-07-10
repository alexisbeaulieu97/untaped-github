from __future__ import annotations

from datetime import UTC, datetime

import pytest

import untaped_github.application as application
import untaped_github.domain as domain
from untaped_github.domain.sweep import (
    ContentConstraint,
    ContentMatch,
    ContentOptions,
    ContentQuestion,
    MatchContext,
    PathConstraint,
    PathFilters,
    PathMatch,
    PathQuestion,
    RefEvaluation,
    RefSelector,
    SweepFailure,
    SweepQuery,
    SweepReport,
    SweepResult,
    SweepScope,
    SweepSummary,
    profile_join,
    ref_matches,
)


def _query(**changes: object) -> SweepQuery:
    values: dict[str, object] = {
        "scope": SweepScope(orgs=("acme",)),
        "question": ContentQuestion(pattern="TODO"),
    }
    values.update(changes)
    return SweepQuery(**values)  # type: ignore[arg-type]


def test_effective_query_serializes_defaults_and_preserves_user_order() -> None:
    query = _query(
        scope=SweepScope(
            orgs=("zeta", "acme"),
            teams=("zeta/platform",),
            repos=("acme/api", "zeta/web"),
            stdin=True,
            include_archived=True,
        ),
        constraints=(
            ContentConstraint(kind="without_content", pattern="DONE"),
            PathConstraint(kind="with_path", pattern="src/**"),
        ),
        path_filters=PathFilters(include=("src/**", "lib/**"), exclude=("src/vendor/**",)),
        refs=RefSelector(profile="branches", globs=("release/*", "hotfix/*")),
        freshness="refresh",
        context=2,
    )

    assert query.to_dict() == {
        "scope": {
            "orgs": ["zeta", "acme"],
            "teams": ["zeta/platform"],
            "repos": ["acme/api", "zeta/web"],
            "stdin": True,
            "include_archived": True,
        },
        "question": {"kind": "content", "pattern": "TODO"},
        "constraints": [
            {"kind": "without_content", "pattern": "DONE"},
            {"kind": "with_path", "pattern": "src/**"},
        ],
        "content_options": {
            "mode": "extended_regex",
            "ignore_case": False,
            "word_regexp": False,
        },
        "path_filters": {
            "include": ["src/**", "lib/**"],
            "exclude": ["src/vendor/**"],
        },
        "refs": {"profile": "branches", "globs": ["release/*", "hotfix/*"]},
        "freshness": "refresh",
        "context": 2,
    }


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: ContentQuestion(pattern="one\ntwo"), "actual newline"),
        (
            lambda: ContentConstraint(kind="with_content", pattern="one\rtwo"),
            "actual newline",
        ),
        (lambda: PathQuestion(pattern="src\n**"), "actual newline"),
        (lambda: PathConstraint(kind="without_path", pattern="src\r**"), "actual newline"),
        (lambda: PathFilters(include=("src\n**",)), "actual newline"),
    ],
)
def test_patterns_reject_actual_newlines(factory: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()  # type: ignore[operator]


def test_query_rejects_negative_context() -> None:
    with pytest.raises(ValueError, match="context must be non-negative"):
        _query(context=-1)


def test_query_rejects_invalid_discriminants() -> None:
    with pytest.raises(ValueError, match="content constraint kind"):
        ContentConstraint(kind="with_path", pattern="README.md")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="content mode"):
        ContentOptions(mode="basic_regex")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="freshness"):
        _query(freshness="stale")


def test_constraints_are_conjunctive_with_primary_on_one_ref() -> None:
    query = _query(
        constraints=(
            ContentConstraint(kind="with_content", pattern="replacement"),
            PathConstraint(kind="without_path", pattern="setup.py"),
        )
    )

    assert ref_matches(
        query,
        RefEvaluation(ref="refs/heads/main", question_hits=1, constraint_hits=(2, 0)),
    )
    assert not ref_matches(
        query,
        RefEvaluation(ref="refs/heads/main", question_hits=1, constraint_hits=(0, 0)),
    )
    assert not ref_matches(
        query,
        RefEvaluation(ref="refs/heads/release", question_hits=0, constraint_hits=(3, 0)),
    )


def test_ref_evaluation_requires_one_count_per_constraint() -> None:
    query = _query(constraints=(PathConstraint(kind="with_path", pattern="README.md"),))

    with pytest.raises(ValueError, match="constraint hit count"):
        ref_matches(
            query,
            RefEvaluation(ref="refs/heads/main", question_hits=1, constraint_hits=()),
        )


def test_complete_report_serialization_is_archival_and_deterministic() -> None:
    synced_at = datetime(2026, 7, 10, 15, tzinfo=UTC)
    oldest_fetched_at = datetime(2026, 7, 10, 14, tzinfo=UTC)
    report = SweepReport(
        query=_query(),
        results=(
            SweepResult(
                full_name="zeta/web",
                clone_url=None,
                refs_matched=("refs/tags/main", "refs/heads/main", "refs/heads/main"),
                matches=(PathMatch(refs=("refs/tags/main",), path="Jenkinsfile"),),
                owners=("@zeta/web", "@zeta/web"),
                synced_at=None,
            ),
            SweepResult(
                full_name="acme/api",
                clone_url="https://github.com/acme/api.git",
                refs_matched=("refs/heads/main",),
                matches=(
                    ContentMatch(
                        refs=("refs/heads/main",),
                        path="src/client.py",
                        start_line=42,
                        end_line=42,
                        content="# TODO: replace client",
                        context=MatchContext(
                            start_line=40,
                            end_line=44,
                            content="def request():\n    pass\n# TODO: replace client",
                        ),
                    ),
                ),
                owners=("@acme/platform",),
                synced_at=synced_at,
            ),
        ),
        failures=(
            SweepFailure(full_name="zeta/broken", stage="scan", reason="git grep failed"),
            SweepFailure(full_name="acme/broken", stage="prepare", reason="fetch failed"),
        ),
        summary=SweepSummary(
            selected=4,
            prepared=3,
            scanned=2,
            matched=2,
            unscanned=2,
            refreshed=1,
            cached=2,
            oldest_fetched_at=oldest_fetched_at,
        ),
    )

    assert report.to_dict() == {
        "query": _query().to_dict(),
        "results": [
            {
                "full_name": "acme/api",
                "clone_url": "https://github.com/acme/api.git",
                "refs_matched": ["refs/heads/main"],
                "matches": [
                    {
                        "kind": "content",
                        "refs": ["refs/heads/main"],
                        "path": "src/client.py",
                        "start_line": 42,
                        "end_line": 42,
                        "content": "# TODO: replace client",
                        "context": {
                            "start_line": 40,
                            "end_line": 44,
                            "content": "def request():\n    pass\n# TODO: replace client",
                        },
                    }
                ],
                "owners": ["@acme/platform"],
                "synced_at": "2026-07-10T15:00:00+00:00",
            },
            {
                "full_name": "zeta/web",
                "clone_url": None,
                "refs_matched": ["refs/heads/main", "refs/tags/main"],
                "matches": [{"kind": "path", "refs": ["refs/tags/main"], "path": "Jenkinsfile"}],
                "owners": ["@zeta/web"],
                "synced_at": None,
            },
        ],
        "failures": [
            {"full_name": "acme/broken", "stage": "prepare", "reason": "fetch failed"},
            {"full_name": "zeta/broken", "stage": "scan", "reason": "git grep failed"},
        ],
        "summary": {
            "selected": 4,
            "prepared": 3,
            "scanned": 2,
            "matched": 2,
            "unscanned": 2,
            "refreshed": 1,
            "cached": 2,
            "oldest_fetched_at": "2026-07-10T14:00:00+00:00",
        },
    }


def test_content_match_omits_absent_context() -> None:
    match = ContentMatch(
        refs=("refs/heads/main",),
        path="README.md",
        start_line=3,
        end_line=3,
        content="TODO",
    )

    assert match.to_dict() == {
        "kind": "content",
        "refs": ["refs/heads/main"],
        "path": "README.md",
        "start_line": 3,
        "end_line": 3,
        "content": "TODO",
    }


@pytest.mark.parametrize(
    ("summary", "message"),
    [
        (
            SweepSummary(0, 0, 0, 1, 0, 0, 0),
            "matched must equal",
        ),
        (
            SweepSummary(1, 0, 0, 0, 0, 0, 0),
            "prepared plus prepare failures",
        ),
        (
            SweepSummary(1, 1, 0, 0, 0, 1, 0),
            "scanned plus scan failures",
        ),
        (
            SweepSummary(0, 0, 0, 0, 1, 0, 0),
            "unscanned must equal",
        ),
        (
            SweepSummary(1, 1, 1, 0, 0, 0, 0),
            "refreshed plus cached",
        ),
    ],
)
def test_report_rejects_summary_invariant_drift(
    summary: SweepSummary,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        SweepReport(
            query=_query(),
            results=(),
            failures=(),
            summary=summary,
        )


def test_result_sorts_matches_by_the_total_serialized_key() -> None:
    result = SweepResult(
        full_name="acme/api",
        clone_url=None,
        refs_matched=("refs/heads/main",),
        matches=(
            PathMatch(refs=("refs/heads/main",), path="z.txt"),
            ContentMatch(
                refs=("refs/heads/main",),
                path="b.txt",
                start_line=2,
                end_line=2,
                content="TODO",
            ),
            PathMatch(refs=("refs/heads/main",), path="a.txt"),
            ContentMatch(
                refs=("refs/heads/main",),
                path="a.txt",
                start_line=1,
                end_line=1,
                content="TODO",
            ),
        ),
        owners=(),
        synced_at=None,
    )

    assert [(match.kind, match.path) for match in result.matches] == [
        ("content", "a.txt"),
        ("content", "b.txt"),
        ("path", "a.txt"),
        ("path", "z.txt"),
    ]


def test_profile_join_lattice() -> None:
    assert profile_join("default", "default") == "default"
    assert profile_join("default", "branches") == "branches"
    assert profile_join("default", "tags") == "tags"
    assert profile_join("branches", "default") == "branches"
    assert profile_join("tags", "default") == "tags"
    assert profile_join("branches", "tags") == "all"
    assert profile_join("tags", "branches") == "all"
    assert profile_join("all", "default") == "all"
    assert profile_join("all", "branches") == "all"
    assert profile_join("tags", "tags") == "tags"


def test_domain_and_application_reexport_report_contracts() -> None:
    assert domain.ContentQuestion is ContentQuestion
    assert domain.SweepReport is SweepReport
    assert application.SweepReport is SweepReport
