from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import yaml

import untaped_github.cli as cli
from untaped_github.cli.sweep_output import emit_sweep_report
from untaped_github.domain import (
    ContentMatch,
    ContentQuestion,
    MatchContext,
    PathMatch,
    SweepFailure,
    SweepQuery,
    SweepReport,
    SweepResult,
    SweepScope,
    SweepSummary,
)

MAIN = "refs/heads/main"
RELEASE = "refs/heads/release/1.0"


def _report() -> SweepReport:
    return SweepReport(
        query=SweepQuery(
            scope=SweepScope(orgs=("acme",)),
            question=ContentQuestion(pattern="TODO"),
            context=2,
        ),
        results=(
            SweepResult(
                full_name="acme/web",
                clone_url="https://github.com/acme/web.git",
                refs_matched=(RELEASE,),
                matches=(PathMatch(refs=(RELEASE,), path="Jenkinsfile"),),
                owners=("@acme/web",),
                synced_at=datetime(2026, 7, 10, 15, 30, tzinfo=UTC),
            ),
            SweepResult(
                full_name="acme/api",
                clone_url="https://github.com/acme/api.git",
                refs_matched=(RELEASE, MAIN),
                matches=(
                    ContentMatch(
                        refs=(RELEASE,),
                        path="src/z.py",
                        start_line=9,
                        end_line=9,
                        content="# TODO z",
                    ),
                    ContentMatch(
                        refs=(RELEASE, MAIN),
                        path="src/a.py",
                        start_line=4,
                        end_line=4,
                        content="# TODO a",
                        context=MatchContext(
                            start_line=2,
                            end_line=6,
                            content="before\n# TODO a\nafter",
                        ),
                    ),
                ),
                owners=("@acme/z", "@acme/a"),
                synced_at=datetime(2026, 7, 10, 15, tzinfo=UTC),
            ),
        ),
        failures=(SweepFailure(full_name="acme/broken", stage="prepare", reason="fetch failed"),),
        summary=SweepSummary(
            selected=3,
            prepared=2,
            scanned=2,
            matched=2,
            unscanned=1,
            refreshed=1,
            cached=1,
            oldest_fetched_at=datetime(2026, 7, 10, 14, tzinfo=UTC),
        ),
    )


def _empty_report(*, failed: bool = False) -> SweepReport:
    failures = (
        (SweepFailure(full_name="acme/broken", stage="prepare", reason="fetch failed"),)
        if failed
        else ()
    )
    return SweepReport(
        query=SweepQuery(
            scope=SweepScope(orgs=("acme",)),
            question=ContentQuestion(pattern="TODO"),
        ),
        results=(),
        failures=failures,
        summary=SweepSummary(
            selected=1 if failed else 0,
            prepared=0,
            scanned=0,
            matched=0,
            unscanned=1 if failed else 0,
            refreshed=0,
            cached=0,
        ),
    )


def test_json_is_a_complete_archival_wrapper(capsys: object) -> None:
    report = _report()

    emit_sweep_report(report, fmt="json", columns=None)

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert json.loads(captured.out) == report.to_dict()
    assert captured.err == ""


def test_json_projection_keeps_wrapper_and_result_coverage_identity(capsys: object) -> None:
    report = _report()

    emit_sweep_report(report, fmt="json", columns=["matches.path", "owners"])

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    rendered = json.loads(captured.out)
    assert rendered["query"] == report.query.to_dict()
    assert rendered["failures"] == [failure.to_dict() for failure in report.failures]
    assert rendered["summary"] == report.summary.to_dict()
    assert rendered["results"] == [
        {
            "full_name": "acme/api",
            "refs_matched": [MAIN, RELEASE],
            "matches": [{"path": "src/a.py"}, {"path": "src/z.py"}],
            "owners": ["@acme/a", "@acme/z"],
        },
        {
            "full_name": "acme/web",
            "refs_matched": [RELEASE],
            "matches": [{"path": "Jenkinsfile"}],
            "owners": ["@acme/web"],
        },
    ]


def test_yaml_uses_the_same_complete_projection_contract(capsys: object) -> None:
    report = _report()

    emit_sweep_report(report, fmt="yaml", columns=["clone_url"])

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    rendered = yaml.safe_load(captured.out)
    assert rendered["query"] == report.query.to_dict()
    assert rendered["failures"] == [failure.to_dict() for failure in report.failures]
    assert rendered["summary"] == report.summary.to_dict()
    assert rendered["results"] == [
        {
            "full_name": "acme/api",
            "refs_matched": [MAIN, RELEASE],
            "clone_url": "https://github.com/acme/api.git",
        },
        {
            "full_name": "acme/web",
            "refs_matched": [RELEASE],
            "clone_url": "https://github.com/acme/web.git",
        },
    ]


def test_table_emits_one_row_per_primary_match_with_result_owners(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "300")

    emit_sweep_report(_report(), fmt="table", columns=None)

    rendered = capsys.readouterr().out
    assert rendered.count("acme/api") == 2
    assert sum("acme/web" in line for line in rendered.splitlines()) == 1
    assert rendered.count("@acme/a, @acme/z") == 2
    assert "src/a.py" in rendered
    assert "src/z.py" in rendered
    assert "Jenkinsfile" in rendered
    assert "before\\n# TODO a\\nafter" in rendered


def test_table_projection_always_keeps_repo_and_match_refs(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")

    emit_sweep_report(_report(), fmt="table", columns=["matches.path"])

    rendered = capsys.readouterr().out
    assert "full_name" in rendered
    assert "matches.refs" in rendered
    assert "matches.path" in rendered
    assert "matches.content" not in rendered
    assert MAIN in rendered


def test_raw_without_columns_emits_each_matching_repository_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_sweep_report(_report(), fmt="raw", columns=None)

    assert capsys.readouterr().out.splitlines() == ["acme/api", "acme/web"]


def test_raw_nested_columns_are_ordered_arrays_on_one_row_per_repository(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_sweep_report(
        _report(),
        fmt="raw",
        columns=["full_name", "matches.path", "matches.start_line"],
    )

    assert capsys.readouterr().out.splitlines() == [
        "acme/api\tsrc/a.py, src/z.py\t4, 9",
        "acme/web\tJenkinsfile\t",
    ]


def test_raw_projection_does_not_force_identity_columns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_sweep_report(_report(), fmt="raw", columns=["owners"])

    assert capsys.readouterr().out.splitlines() == [
        "@acme/a, @acme/z",
        "@acme/web",
    ]


def test_pipe_ignores_columns_and_emits_complete_result_records(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _report()

    emit_sweep_report(report, fmt="pipe", columns=["not.a.selector"])

    envelopes = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [envelope["untaped"] for envelope in envelopes] == ["1", "1"]
    assert [envelope["kind"] for envelope in envelopes] == [
        "github.sweep_result",
        "github.sweep_result",
    ]
    assert [envelope["record"] for envelope in envelopes] == [
        result.to_dict() for result in report.results
    ]


def test_pipe_ignores_columns_question_mark(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _report()

    emit_sweep_report(report, fmt="pipe", columns=["?"])

    captured = capsys.readouterr()
    assert captured.err == ""
    assert [json.loads(line)["record"] for line in captured.out.splitlines()] == [
        result.to_dict() for result in report.results
    ]


def test_columns_question_mark_lists_exact_nested_selectors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_sweep_report(_report(), fmt="json", columns=["?"])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [
        "available columns:",
        "  full_name",
        "  clone_url",
        "  refs_matched",
        "  matches.kind",
        "  matches.refs",
        "  matches.path",
        "  matches.start_line",
        "  matches.end_line",
        "  matches.content",
        "  matches.context",
        "  owners",
        "  synced_at",
    ]


@pytest.mark.parametrize("fmt", ["json", "yaml", "table", "raw"])
def test_unknown_column_is_a_descriptive_usage_error(
    fmt: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        emit_sweep_report(_report(), fmt=fmt, columns=["matches.line"])  # type: ignore[arg-type]

    assert raised.value.code == 2
    assert capsys.readouterr().err == (
        "error: unknown sweep column selector 'matches.line'; "
        "use --columns ? to list valid selectors\n"
    )


@pytest.mark.parametrize("fmt", ["table", "raw", "pipe"])
@pytest.mark.parametrize("failed", [False, True])
def test_result_only_formats_are_empty_for_no_matches_even_with_failures(
    fmt: str,
    failed: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_sweep_report(_empty_report(failed=failed), fmt=fmt, columns=None)  # type: ignore[arg-type]

    assert capsys.readouterr().out == ""


def test_empty_json_still_serializes_the_complete_wrapper(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _empty_report(failed=True)

    emit_sweep_report(report, fmt="json", columns=None)

    assert json.loads(capsys.readouterr().out) == report.to_dict()


def test_cli_package_reexports_the_sweep_renderer() -> None:
    assert cli.emit_sweep_report is emit_sweep_report
