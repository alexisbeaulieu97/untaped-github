# untaped-github

`untaped-github` is a standalone GitHub CLI built on the
[`untaped`](https://github.com/alexisbeaulieu97/untaped) SDK. It provides
authenticated user inspection, complete org/team repository inventory,
GitHub REST search across repositories, code, issues/PRs, and users/orgs,
and a question-first `sweep` command for repeated team-wide code and file
presence checks over a managed local Git corpus. It also ships the shared
`config`, `profile`, and `skills` command groups every untaped tool ships.

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
untaped-github repos list [PATTERN] [--org ORG]... [--team ORG/SLUG|SLUG]...
untaped-github sweep --org ORG|--team ORG/SLUG|--repo OWNER/NAME --grep PATTERN
untaped-github sweep --org ORG --has-file GLOB [--not-grep PATTERN] [--fail-on-match]
untaped-github cache status|worktree ...
untaped-github cache clean --repo OWNER/NAME|--all|--prune [--yes|-y]
untaped-github search repos [QUERY]
untaped-github search code [QUERY]
untaped-github search issues [QUERY]
untaped-github search users [QUERY]
untaped-github config|profile|skills ...
```

Examples:

```bash
untaped-github sweep --org acme --grep 'old_api' --not-grep 'new_api'
untaped-github sweep --team acme/platform --grep 'log4j' --fail-on-match
untaped-github sweep --org acme --grep 'old_api' \
  --format raw --columns clone_url \
  | untaped-workspace add --stdin --workspace remediation
untaped-github cache status --format table
```

See [docs/github.md](./docs/github.md) for command details and examples.

## Public Client API

Sibling untaped tools may import `GithubClient`, `GithubSettings`,
`GithubGraphqlError`, repository inventory helpers such as
`ResolveRepositoryInventory`, and the batched ref-probe result models from
`untaped_github`. `GithubClient.batch_repo_refs(...)` probes branch/tag refs;
`GithubClient.batch_default_branch_refs(...)` probes only default branches with
a connection-free GraphQL query. Both return `BatchRepoRefsResult`, including
GraphQL cost, remaining, reset metadata, and per-repo transient failures from
bounded GraphQL retry/adaptive-split handling.

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
contracts. See [docs/release.md](./docs/release.md) for the PyPI/TestPyPI
release workflow.

## Security

Please report suspected vulnerabilities privately. See
[SECURITY.md](./SECURITY.md).

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) and [AGENTS.md](./AGENTS.md) for the
local workflow, architecture rules, and GitHub-specific contracts.

## License

MIT. See [LICENSE](./LICENSE).
