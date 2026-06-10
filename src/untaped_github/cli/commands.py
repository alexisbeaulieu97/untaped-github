"""Cyclopts commands for the GitHub domain."""

from __future__ import annotations

from untaped import (
    ColumnsOption,
    FormatOption,
    ProfileOverrideOption,
    create_app,
    echo,
    report_errors,
)

from untaped_github.cli._client import open_client
from untaped_github.cli._rendering import render_rows
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
    profile: ProfileOverrideOption = None,
) -> None:
    """Show the authenticated GitHub user (``GET /user``)."""
    from untaped_github.application import WhoAmI  # noqa: PLC0415

    with report_errors(), open_client(profile) as client:
        user = WhoAmI(client)()
        echo(render_rows([user.model_dump()], fmt=fmt, columns=columns))


app.command(search_app, name="search")
