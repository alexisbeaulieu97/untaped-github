# untaped-github

`untaped-github` is a standalone GitHub CLI built on the
[`untaped`](https://github.com/alexisbeaulieu97/untaped) SDK. It provides
authenticated user inspection, complete org/team repository inventory,
GitHub REST search across repositories, code, issues/PRs, and users/orgs,
plus the shared `config`, `profile`, and `skills` command groups every
untaped tool ships.

## Install

```bash
uv tool install untaped-github
```

## Configure

```bash
untaped-github config set token --prompt   # bare key → this tool's section
untaped-github whoami
untaped-github --profile work whoami        # --profile works in any position
```

For GitHub Enterprise Server, configure the API base URL explicitly:

```bash
untaped-github config set base_url https://github.example.com/api/v3
```

Settings are stored per profile in `~/.untaped/config.yml` (shared with the
other untaped tools). Shared SDK settings such as `ui.theme` and `http.*` are
per-profile keys too (e.g. `untaped-github config set http.verify_ssl false`).

## Commands

```text
untaped-github whoami
untaped-github repos list [PATTERN] --org <org> | --team <org>/<slug>
untaped-github search repos [QUERY]
untaped-github search code [QUERY]
untaped-github search issues [QUERY]
untaped-github search users [QUERY]
untaped-github config|profile|skills ...
```

See [docs/github.md](./docs/github.md) for command details and examples.

## Development

```bash
uv sync
uv run pytest
uv run mypy
uv run ruff check --fix
uv run ruff format
uv run untaped-github --help
```

See [AGENTS.md](./AGENTS.md) for architecture rules and GitHub-specific
contracts.
