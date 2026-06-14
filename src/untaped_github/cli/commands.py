"""Cyclopts commands for the GitHub domain."""

from __future__ import annotations

from untaped.api import (
    ColumnsOption,
    FormatOption,
    create_app,
    echo,
    render_rows,
    report_errors,
)

from untaped_github.cli._client import open_client
from untaped_github.cli.search_commands import app as search_app

app = create_app(
    name="github",
    help="Inspect and search GitHub from the authenticated user's account.",
)


@app.command(name="whoami")
def whoami_command(
    *,
    fmt: FormatOption = "table",
    columns: ColumnsOption = None,
) -> None:
    """Show the authenticated GitHub user (``GET /user``)."""
    from untaped_github.application import WhoAmI  # noqa: PLC0415

    with report_errors(), open_client() as (client, ui):
        with ui.progress("Fetching authenticated user…"):
            user = WhoAmI(client)()
        echo(render_rows([user.model_dump()], fmt=fmt, columns=columns, kind="github.user"))


app.command(search_app, name="search")
