# untaped-github

`untaped-github` is the GitHub plugin for
[`untaped`](https://github.com/alexisbeaulieu97/untaped). It adds the
`untaped github` command group for authenticated user inspection and
GitHub REST search across repositories, code, issues/PRs, and users/orgs.

## Install

Install both `untaped` and this plugin from git:

```bash
uv tool install "git+https://github.com/alexisbeaulieu97/untaped.git" \
  --with "untaped-github @ git+https://github.com/alexisbeaulieu97/untaped-github.git" \
  --no-sources \
  --force
```

To let `untaped plugins` remember that desired plugin state, record the
plugin without syncing, then rebuild the tool from the same source spec:

```bash
untaped plugins add "untaped-github @ git+https://github.com/alexisbeaulieu97/untaped-github.git" --no-sync
untaped plugins sync --tool-spec "git+https://github.com/alexisbeaulieu97/untaped.git"
```

For local editable core development, point sync at the local `untaped`
checkout:

```bash
untaped plugins add "untaped-github @ git+https://github.com/alexisbeaulieu97/untaped-github.git" --no-sync
untaped plugins sync --tool-spec /path/to/untaped --editable-tool
```

## Configure

```bash
untaped config set github.token ghp_xxx
untaped github whoami
```

For GitHub Enterprise Server, configure the API base URL explicitly:

```bash
untaped config set github.base_url https://github.example.com/api/v3
```

## Commands

```text
untaped github whoami
untaped github search repos [QUERY]
untaped github search code [QUERY]
untaped github search issues [QUERY]
untaped github search users [QUERY]
```

See [docs/github.md](./docs/github.md) for command details and examples.

## Development

```bash
uv sync
uv run pytest
uv run mypy
uv run ruff check --fix
uv run ruff format
uv run untaped github --help
```

See [AGENTS.md](./AGENTS.md) for architecture rules and GitHub-specific
contracts.
