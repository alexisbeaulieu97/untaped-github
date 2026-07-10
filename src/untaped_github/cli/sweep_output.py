"""Format-specific rendering for complete sweep reports."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from untaped.api import OutputFormat, echo, emit, raise_usage

if TYPE_CHECKING:
    from untaped_github.domain import SweepReport, SweepResult


_RESULT_IDENTITY = ("full_name", "refs_matched")
SWEEP_COLUMN_SELECTORS = (
    "full_name",
    "clone_url",
    "refs_matched",
    "matches.kind",
    "matches.refs",
    "matches.path",
    "matches.start_line",
    "matches.end_line",
    "matches.content",
    "matches.context",
    "owners",
    "synced_at",
)


def emit_sweep_report(
    report: SweepReport,
    *,
    fmt: OutputFormat,
    columns: list[str] | None,
) -> None:
    """Write a sweep report using the format-specific public contract."""
    if columns == ["?"]:
        echo("available columns:", err=True)
        for selector in SWEEP_COLUMN_SELECTORS:
            echo(f"  {selector}", err=True)
        return
    if fmt != "pipe":
        _validate_columns(columns)
    if fmt in ("json", "yaml"):
        emit(_structured_report(report, columns), fmt=fmt)
        return
    if fmt == "table":
        emit(_table_rows(report, columns), fmt=fmt)
        return
    if fmt == "raw":
        emit(_raw_rows(report, columns), fmt=fmt, columns=columns)
        return
    if fmt == "pipe":
        emit(
            [result.to_dict() for result in report.results],
            fmt=fmt,
            kind="github.sweep_result",
        )
        return
    raise NotImplementedError(f"sweep output format is not implemented: {fmt}")


def _validate_columns(columns: list[str] | None) -> None:
    for selector in columns or ():
        if selector not in SWEEP_COLUMN_SELECTORS:
            raise_usage(
                f"unknown sweep column selector {selector!r}; "
                "use --columns ? to list valid selectors"
            )


def _structured_report(report: SweepReport, columns: list[str] | None) -> dict[str, object]:
    if columns is None:
        return report.to_dict()
    return {
        "query": report.query.to_dict(),
        "results": [_project_result(result, columns) for result in report.results],
        "failures": [failure.to_dict() for failure in report.failures],
        "summary": report.summary.to_dict(),
    }


def _project_result(result: SweepResult, columns: list[str]) -> dict[str, object]:
    source = result.to_dict()
    projected: dict[str, object] = {name: source[name] for name in _RESULT_IDENTITY}
    match_fields = [
        column.removeprefix("matches.") for column in columns if column.startswith("matches.")
    ]
    for column in columns:
        if column.startswith("matches."):
            continue
        projected[column] = source[column]
    if match_fields:
        projected["matches"] = [
            {field: match[field] for field in match_fields if field in match}
            for match in _matches(source)
        ]
    return projected


def _table_rows(report: SweepReport, columns: list[str] | None) -> list[dict[str, object]]:
    result_rows = [(result, result.to_dict()) for result in report.results]
    if columns is None:
        has_content = any(
            match["kind"] == "content" for _, result in result_rows for match in _matches(result)
        )
        has_context = any(
            "context" in match for _, result in result_rows for match in _matches(result)
        )
        columns = ["matches.path"]
        if has_content:
            columns.extend(["matches.start_line", "matches.end_line", "matches.content"])
        if has_context:
            columns.append("matches.context")
        columns.append("owners")

    selected = list(dict.fromkeys(("full_name", "matches.refs", *columns)))
    rows: list[dict[str, object]] = []
    for _, result in result_rows:
        for match in _matches(result):
            row: dict[str, object] = {}
            for selector in selected:
                if selector.startswith("matches."):
                    row[selector] = match.get(selector.removeprefix("matches."))
                else:
                    row[selector] = result[selector]
            rows.append(row)
    return rows


def _raw_rows(report: SweepReport, columns: list[str] | None) -> list[dict[str, object]]:
    if columns is None:
        return [{"full_name": result.full_name} for result in report.results]

    rows: list[dict[str, object]] = []
    for result in report.results:
        source = result.to_dict()
        row: dict[str, object] = {}
        match_values: dict[str, object] = {}
        for selector in columns:
            if selector.startswith("matches."):
                field = selector.removeprefix("matches.")
                match_values[field] = [match[field] for match in _matches(source) if field in match]
            else:
                row[selector] = source[selector]
        if match_values:
            row["matches"] = match_values
        rows.append(row)
    return rows


def _matches(result: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", result["matches"])


__all__ = ["SWEEP_COLUMN_SELECTORS", "emit_sweep_report"]
