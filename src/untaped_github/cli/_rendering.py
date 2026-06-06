"""Rendering helpers for GitHub CLI row output."""

from __future__ import annotations

from collections.abc import Sequence

from untaped import OutputFormat, UiContext, ui_context

Row = dict[str, object]


def render_rows(
    rows: Sequence[Row],
    *,
    fmt: OutputFormat,
    columns: list[str] | None,
) -> str:
    """Render GitHub rows through the right UI context for the output format."""
    if fmt == "table":
        return ui_context().collection(rows, fmt=fmt, columns=columns)
    return UiContext().collection(rows, fmt=fmt, columns=columns)
