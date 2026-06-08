# untaped-github

`untaped-github` is the GitHub plugin for
[`untaped`](https://github.com/alexisbeaulieu97/untaped). It adds the
`untaped github` command group for authenticated user inspection and
GitHub REST search across repositories, code, issues/PRs, and users/orgs.

## Install

Install both `untaped` and this plugin from git:

```bash
uv tool install "git+https://github.com/alexisbeaulieu97/untaped.git@v0.1.3" \
  --with "untaped-github @ git+https://github.com/alexisbeaulieu97/untaped-github.git@v0.2.0" \
  --no-sources \
  --force
```

For managed plugin state, editable source installs, and multi-plugin sync
examples, see the core
[`untaped` plugin docs](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/plugins.md).

This plugin also contributes the `untaped-github` agent skill. After the
plugin is installed, use the core
[`untaped` agent skill docs](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/skills.md)
to install it for Codex or Claude.

## Configure

```bash
untaped config set github.token ghp_xxx
untaped github whoami
untaped github whoami --profile work
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
