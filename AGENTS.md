# AGENTS.md - `untaped-github`

Single source of truth for this standalone plugin repo. If you change
architecture, command behavior, settings behavior, or the development
workflow, update this file in the same commit.

## Mission

`untaped-github` is an `untaped` plugin. It owns the `untaped github`
command group for authenticated user inspection and GitHub REST search
(`repos`, `code`, `issues`, `users`). `untaped` core owns the binary,
plugin discovery, config/profile resolution, output helpers, HTTP/TLS
primitives, and shared errors.

## Hard Rules

1. **Keep `AGENTS.md` up to date.** Architecture changes and new command
   patterns must be documented here.
2. **Prefer `uv` commands over manual dependency edits.** Use `uv add` and
   `uv add --group dev`; hand-edit tool config only.
3. **Expose the plugin through the `untaped.plugins` entry point.**
   `github = "untaped_github.plugin:plugin"` is the public integration point.
   The plugin object must expose `id = "github"`, literal
   `untaped_api_version = 1`, and `register(registry)`.
4. **Use the 4-layer DDD layout.** `cli -> application -> domain`, with
   `infrastructure -> domain`; `application` and `infrastructure` must not
   import each other at runtime.
5. **Declare ports in `application/ports.py`.** Use cases depend on the
   narrowest `Protocol`; concrete adapters satisfy ports structurally.
6. **Use absolute imports.** `from untaped_github...` and `from untaped...`,
   never relative imports.
7. **Every source module has a module docstring.** Re-export `__init__.py`
   files are exempt.
8. **Every Typer app and every command with required args sets
   `no_args_is_help=True`.**
9. **stdout is data only.** Prompts, progress, and status messages go to
   stderr via `typer.echo(..., err=True)`.
10. **Pipe-friendly commands keep stable raw identifiers.** `GithubUser`
    starts with `login`; repo search rows start with `full_name`; issue
    search rows start with `repo`; user search rows start with `id`; code
    search rows start with `name`.
11. **Secrets stay secret.** `GithubSettings.token` is a `SecretStr`; call
    `.get_secret_value()` only inside the HTTP adapter.
12. **Use `resolve_verify(http)` for GitHub HTTP clients.** Never hard-code
    TLS verification policy.
13. **Finish with verification.** Run `uv run ruff check --fix`,
    `uv run ruff format`, `uv run mypy`, and `uv run pytest`.

## Architecture

```text
src/untaped_github/
├── __init__.py           # re-exports app
├── plugin.py             # entry-point plugin object
├── settings.py           # plugin-owned config model
├── cli/                  # Typer commands; composition root
├── application/          # use cases and ports
├── domain/               # pure models and query value objects
└── infrastructure/       # GitHub REST client and pagination
```

The plugin object registers `GithubSettings` as the `github` profile
settings section, mounts the Typer app as the root `github` command, and
registers the packaged `untaped-github` agent skill. Plugin code reads typed
settings with
`get_config_section("github", GithubSettings)`, not a global aggregate
`settings.github` attribute.

## Auth Model

GitHub uses bearer-token auth. The token is a `SecretStr` read through
`get_config_section("github", GithubSettings)` or `UNTAPED_GITHUB__TOKEN`.
The CLI composition root reads it once and passes the narrowed
`GithubSettings` into `GithubClient`. Adapters never read the full core
settings aggregate directly.

Commands that read settings expose the core command-local
`ProfileOverrideOption` as `--profile` and pass it into
`open_client(profile)`. `open_client` applies `profile_override(profile)`
around both core HTTP settings and the `github` profile section lookup.

`GithubClient.__init__` fail-fasts with `ConfigError` if the token is
missing or whitespace-only. There is no anonymous-mode fallback;
unauthenticated GitHub is rate-limited enough that supporting it inline
would produce misleading behavior.

## Base URL: GitHub vs GHE

`GithubSettings.base_url` defaults to `https://api.github.com`. For GitHub
Enterprise Server, point it at `https://<host>/api/v3`. Trailing slashes
are stripped at client construction so URL joins are clean. No
auto-detection: the user configures it explicitly.

## Settings Sub-model

`GithubClient.__init__` takes `GithubSettings` from
`untaped_github.settings` directly. Do not add a mirror `GithubConfig`
class unless the adapter needs extra invariants beyond the Pydantic schema.
Adding a field is a two-place edit: `GithubSettings` plus the constructor
or call site that consumes it.

## HTTP Wiring

`GithubClient` wraps `untaped.HttpClient` with these headers:

- `Accept: application/vnd.github+json`
- `X-GitHub-Api-Version: 2022-11-28`
- `Authorization: Bearer <token>`

TLS comes from `resolve_verify(http)` using core `HttpSettings`.

## Public Client API

`untaped_github` intentionally re-exports `GithubClient` and
`GithubSettings` for sibling plugins that need GitHub access. Keep this
surface small and tested. Cross-plugin consumers may use repository
metadata, org/team repository listing, matching refs, tree reads, and raw
content reads. Add missing GitHub operations here rather than duplicating a
GitHub client in another plugin or importing private CLI helpers.

## Rate Limiting

Authenticated GitHub gives 5000 requests/hour overall and a separate
30 requests/minute budget for `/search/*`. `whoami` is one call; `search`
paginates 100 rows per page and stops at `--limit` (default `30`). The
30-row default keeps casual queries to one round trip against the search
budget. `--limit 1000` opts into GitHub's hard search ceiling. The CLI may
accept larger values, but the paginator stops once GitHub stops returning a
`next` link.

Future high-volume features should honor `X-RateLimit-Remaining` and
`X-RateLimit-Reset`, and back off on `429 Too Many Requests`.

## Search

`search` is a Typer sub-app mounted on the root `github` app, with one
subcommand per GitHub search endpoint:

| Subcommand     | Endpoint               | Key filters |
| -------------- | ---------------------- | ----------- |
| `search repos` | `/search/repositories` | `--name`, `--language`, `--archived/--no-archived`, `--fork/--no-fork`, `--visibility`, `--sort` |
| `search code`  | `/search/code`         | `--language`, `--filename`, `--path`, `--extension` |
| `search issues`| `/search/issues`       | `--state`, `--kind issue\|pr`, `--author`, `--assignee`, `--label`, `--mentions` |
| `search users` | `/search/users`        | `--kind user\|org`, `--location`, `--language` |

The three scoped subcommands (`repos`, `code`, `issues`) accept `--user`,
`--org` (repeatable), `--repo` (repeatable), `--repo-stdin`, and `--team`
(repeatable). `search users` does not; GitHub's user-search endpoint
ignores those qualifiers, so exposing them would mislead. All search
commands share `--limit` and core `--format/-f` + `--columns/-c`.

Repeated `--repo` scopes render as one parenthesized OR group, e.g.
`(repo:acme/api OR repo:acme/web)`, because GitHub treats whitespace as
AND and a multi-repo search must match any listed repository. A single
repo keeps the simple `repo:owner/name` shape.

`search code` does not accept `--sort`; GitHub no longer supports sorting
code search results.

### `SearchLimitOption`

`cli/search_commands.py` defines package-local `SearchLimitOption` and each
subcommand supplies the default at the call site (`limit: SearchLimitOption =
30`). Keep the alias local because its help text names GitHub's search cap,
which is plugin-specific rather than core plumbing.

### Default Scope Rule

`SearchRepos`, `SearchCode`, and `SearchIssues` inject `user:@me` whenever
the user passes none of `--user`, `--org`, `--repo`, or `--team`. This keeps
the bare command scoped to the authenticated user's own work. `SearchUsers`
does not inject anything because GitHub user search ignores those qualifiers.

### Team-to-repo Resolution

There is no `team:` qualifier in GitHub search. `--team ORG/SLUG` is the
preferred self-contained form; `--team SLUG --org ORG` stays as a
convenience when there is exactly one org. CLI parsing turns both forms
into `TeamScope(org, slug)` objects, then the use case calls
`GET /orgs/{org}/teams/{slug}/repos` and expands the result into the same
parenthesized OR repo group used by explicit repeated `--repo` flags. The
use case bounds each team at `MAX_TEAM_REPO_QUALIFIERS + 1` with
`itertools.islice`; if the cap is exceeded, keep the first N and emit a
stderr warning through the injected `warn` callback. Keep the cap
conservative: the generated OR group expands quickly under GitHub's search
query length budget, and users can pass explicit `--repo` scopes when they
intentionally want a wider query.

`--repo-stdin` reads newline-separated `owner/name` scopes with core
`read_identifiers([], stdin=True)` and appends them to explicit `--repo`
values before the filter object is constructed. Keep this in the CLI layer:
application use cases should receive already-parsed `repos` and
`TeamScope` values, not own stdin.

### Pagination

`paginate_search` and `paginate_list` follow GitHub RFC 5988 `Link` headers
until exhausted or `--limit` is hit. Search payloads nest rows under `items`;
list payloads, such as team repos, return JSON arrays.

Two efficiency/defense rules are load-bearing:

- When `--limit < per_page`, the first request asks only for `limit` rows.
- The paginator visits at most `_MAX_PAGES` URLs and refuses to follow a
  `next` link that matches the current or any previously visited URL.

## Layering

- `domain/`: `GithubUser`, `RepoResult`, `CodeResult`, `IssueResult`,
  `UserResult`, and frozen filter value objects in `queries.py`. Query
  objects render GitHub `q=` strings and do no I/O.
- `application/`: `WhoAmI`, `SearchRepos`, `SearchCode`, `SearchIssues`,
  `SearchUsers`, and their `Protocol` ports. Scope defaulting and
  team-to-repo resolution live here.
- `infrastructure/`: `GithubClient` and `pagination.py`. Adapters satisfy
  application ports structurally and do not import `application`.
- `cli/`: composition root. `cli/_client.open_client` reads the plugin config
  and returns a context-managed `GithubClient`; top-level commands use it.

## Development Workflow

```bash
uv sync
uv run pre-commit install
uv run pytest
uv run mypy
uv run ruff check --fix
uv run ruff format
uv run untaped github --help
```

Use `pytest --no-cov` for tight local loops. Full `pytest` enforces the
coverage gate.

## Recipe: Add A GitHub Subcommand

1. Write a use-case test with a stub satisfying the narrowest port.
2. Add or narrow a port in `application/ports.py` if the command needs new
   service behavior.
3. Add a domain model or query value object in `domain/` when needed.
4. Add the HTTP method to `infrastructure/github_client.py` and keep
   pagination details in `infrastructure/pagination.py`.
5. Wire the Typer command in `cli/commands.py` or `cli/search_commands.py`;
   keep stdout data-only and expose `--format`/`--columns` for data output.
6. If the command emits rows, update `tests/unit/test_format_raw_first_key.py`.
7. Run `uv run untaped github <command> --help` plus the full verification
   commands above.

## See Also

- [`untaped` core](https://github.com/alexisbeaulieu97/untaped) - plugin
  runtime, settings registry, config-file helpers, output helpers.
- [`untaped` configuration docs](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/configuration.md)
  - user-facing profile, config, secrets, and TLS behavior.
