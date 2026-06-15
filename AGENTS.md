# AGENTS.md - `untaped-github`

Single source of truth for this standalone CLI repo. If you change
architecture, command behavior, settings behavior, or the development
workflow, update this file in the same commit.

## Mission

`untaped-github` is a standalone CLI built on the `untaped` SDK, invoked as
`untaped-github`. It provides authenticated user inspection and GitHub REST
search (`repos`, `code`, `issues`, `users`). The `untaped` SDK owns config
loading, output helpers, HTTP/TLS primitives, profile selection, and shared
errors. Profile selection is built into the SDK and works in any token
position.

## Hard Rules

1. **Keep `AGENTS.md` and the packaged skill up to date.** Architecture
   changes, new command patterns, settings changes, and major GitHub
   workflow changes must be documented here and in
   `src/untaped_github/skills/untaped-github/SKILL.md`.
2. **Prefer `uv` commands over manual dependency edits.** Use `uv add` and
   `uv add --group dev`; hand-edit tool config only.
3. **Expose the CLI through the SDK entry point.**
   `untaped_github/__init__.py` re-exports the Cyclopts `app` (and the
   public client API) so the SDK's launcher can mount it as the
   `untaped-github` command. Keep the root API import-light:
   `__init__.py` re-exports `app` only through a PEP 562 module
   `__getattr__` so importing the package never eagerly imports the command
   tree.
4. **Use the 4-layer DDD layout.** `cli -> application -> domain`, with
   `infrastructure -> domain`; `application` and `infrastructure` must not
   import each other at runtime.
5. **Declare ports in `application/ports.py`.** Use cases depend on the
   narrowest `Protocol`; concrete adapters satisfy ports structurally.
6. **Use absolute imports, and import the SDK from `untaped.api`.**
   `from untaped_github...` and `from untaped.api import ...`, never
   relative imports. `untaped.api` is the supported SDK surface;
   only tests may reach for `untaped.testing` (and SDK internals such as
   `untaped.main`/`untaped.settings` when a name is not exported by
   `untaped.api`).
7. **Every source module has a module docstring.** Re-export `__init__.py`
   files are exempt.
8. **Cyclopts command signatures are explicit.** Use
   `Annotated[..., Parameter(...)]` and name documented commands/options
   explicitly. Required inputs are required positional-only params
   (`Parameter(help=...)` before `/`); a missing value renders
   `error: ... requires an argument` (exit 2) automatically — never an
   optional default plus a manual help dance.
9. **stdout is data only.** Prompts, progress, and status messages go to
   stderr via `echo(..., err=True)`.
10. **Pipe-friendly commands keep stable raw first-key identifiers.** These
    raw first-key contracts are load-bearing: `GithubUser` starts with
    `login`; repo search rows start with `full_name`; issue search rows
    start with `repo`; user search rows start with `id`; code search rows
    start with `name`.
11. **Human table output honors global UI settings.** GitHub row commands
    render `--format table` through the active settings-backed
    `ui_context().collection(...)` so global themes and
    `ui.collection_view` apply.
12. **Structured output bypasses global themes.** `--format json`, `yaml`,
    and `raw` render through a plain `UiContext().collection(...)` so
    invalid or missing themes never break pipe-friendly output.
13. **Secrets stay secret.** `GithubSettings.token` is a `SecretStr`; call
    `.get_secret_value()` only inside the HTTP adapter.
14. **Build GitHub HTTP clients with `connected_client(...)`.** The SDK owns
    required-field validation, bearer auth, base-URL normalization, and TLS
    resolution (`resolve_verify`); never hard-code TLS verification policy.
15. **Finish with verification.** Run `uv run ruff check --fix`,
    `uv run ruff format`, `uv run mypy`, and `uv run pytest`.

## Architecture

```text
src/untaped_github/
├── __init__.py           # small root API: GithubClient, GithubSettings, lazy app
├── settings.py           # config model for this tool's `github` section
├── cli/                  # Cyclopts commands; composition root
├── application/          # use cases and ports
├── domain/               # pure models and query value objects
└── infrastructure/       # GithubClient, REST pagination, GraphQL ref probe
```

The CLI declares `GithubSettings` as its `github` settings section, mounts
the Cyclopts `app` as the root command, and ships the packaged
`untaped-github` agent skill. Keep that static skill asset current with major
GitHub workflow changes. Command code reads typed settings with
`plugin_context().section("github", GithubSettings)`, not a global
aggregate `settings.github` attribute.

## Auth Model

GitHub uses bearer-token auth. The token is a `SecretStr` read through
`plugin_context().section("github", GithubSettings)` or
`UNTAPED_GITHUB__TOKEN`. The CLI composition root reads it once and passes
the narrowed `GithubSettings` into `GithubClient`. Adapters never read the
full SDK settings aggregate directly.

Profile selection is owned by the SDK: the `--profile` option works in any
token position, so commands define no command-local `--profile` parameter.
Commands call bare `open_client()`, which calls `plugin_context()`; the SDK
resolves settings exactly once under the active profile and returns a frozen
context (`ctx.section(...)` for the `github` section, `ctx.http` for SDK
HTTP settings) without leaking into ambient process state.

`GithubClient.__init__` fail-fasts with `ConfigError` (via the SDK's
`connected_client` required-field validation) if the token is missing or
whitespace-only. There is no anonymous-mode fallback;
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

`GithubClient` builds its `HttpClient` through the SDK's
`connected_client(config, section="github", headers=..., http=...)`, which
validates `base_url` and `token`, strips/normalizes them, and sets:

- `Accept: application/vnd.github+json`
- `X-GitHub-Api-Version: 2022-11-28`
- `Authorization: Bearer <token>` (added by `connected_client`)

TLS comes from `resolve_verify(http)` inside `connected_client`, using
the SDK's `HttpSettings`.

## Public Client API

`untaped_github` intentionally re-exports `GithubClient` and
`GithubSettings` for sibling untaped tools that need GitHub access, plus the
`batch_repo_refs` result models (`BatchRepoRefsResult`, `RepoRefs`,
`RepoRef`). Keep this surface small and tested. Library consumers
may use repository metadata, org/team repository listing, matching refs,
batched ref probing, tree reads, and raw content reads. Add missing
GitHub operations here rather than duplicating a GitHub client in
another tool or importing private CLI helpers.

## GraphQL Batched Ref Probe

`GithubClient.batch_repo_refs(repos, *, kinds=("heads", "tags"),
chunk_size=50)` probes branch/tag heads for many `owner/name` repos in
few API calls (~1500 repos in ~30 POSTs at the default chunk size). It
is the freshness probe consumed by sibling untaped tools instead of per-repo
`git ls-remote`.

Mechanics live in `infrastructure/graphql.py`, isolated the same way
`pagination.py` isolates Link-header mechanics; `github_client.py` only
wires `self._http.post_json(...)` at the derived endpoint. Load-bearing
behaviors:

- **Endpoint derivation is absolute.** `https://api.github.com` →
  `https://api.github.com/graphql`; GHE `https://<host>/api/v3` →
  `https://<host>/api/graphql`. The httpx client carries the REST
  `base_url`, so a relative path would join to `/api/v3/graphql` on GHE.
- **Aliases `r0..rN` map back to input order** within each chunk; each
  chunk is one POST built from escaped GraphQL literals (`json.dumps`).
- **Annotated tags are peeled up to two levels.** The query selects
  nested `target { oid }` two levels deep (covers tags-of-tags);
  `RepoRef.sha` is the deepest fetched oid, so deeper tag chains return
  the innermost fetched oid rather than the final commit.
- **`kinds=("heads",)` omits the tags connection entirely**, halving the
  per-repo point cost.
- **Missing repos don't raise.** A `null` data node plus a `NOT_FOUND`
  or `FORBIDDEN` error with `path: ["rX"]` lands the input full name in
  `BatchRepoRefsResult.missing`; any other GraphQL error raises
  `UntapedError`.
- **Ref-pagination overflow** (>100 refs in a namespace) is followed
  serially with single-repo `after: <cursor>` queries until exhausted.
- **5xx split-retry.** GitHub intermittently 502s on large aliased
  queries; the chunk is retried once split in half, and a half that
  still 5xxs raises `HttpError`.

GraphQL has its own 5000 points/hour budget (separate from REST), at
roughly one point per repo per ref connection. A full heads+tags probe
of 1500 repos costs ≈ 3000 points — callers should watch
`BatchRepoRefsResult.rate_limit_remaining` (GraphQL
`rateLimit.remaining`) and warn when the budget runs low.

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

GraphQL (`batch_repo_refs`) draws on a separate 5000 points/hour budget;
see "GraphQL Batched Ref Probe" above for cost math.

## Search

`search` is a Cyclopts sub-app mounted on the root `github` app, with one
subcommand per GitHub search endpoint:

| Subcommand     | Endpoint               | Key filters |
| -------------- | ---------------------- | ----------- |
| `search repos` | `/search/repositories` | `--name`, `--language`, `--archived/--no-archived`, `--fork/--no-fork`, `--visibility`, `--sort` |
| `search code`  | `/search/code`         | `--language`, `--filename`, `--path`, `--extension` |
| `search issues`| `/search/issues`       | `--state`, `--kind issue\|pr`, `--author`, `--assignee`, `--label`, `--mentions`, `--sort` |
| `search users` | `/search/users`        | `--kind user\|org`, `--location`, `--language`, `--sort` |

The three scoped subcommands (`repos`, `code`, `issues`) accept `--user`,
`--org` (repeatable), `--repo` (repeatable), `--repo-stdin`, and
`--team ORG/SLUG` (repeatable). `search users` does not; GitHub's user-search endpoint
ignores those qualifiers, so exposing them would mislead. All search
commands share `--limit` and the SDK's `--format/-f` + `--columns/-c`.

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
which is specific to this tool rather than SDK plumbing.

### Default Scope Rule

`SearchRepos`, `SearchCode`, and `SearchIssues` inject `user:@me` whenever
the user passes none of `--user`, `--org`, `--repo`, or `--team`. This keeps
the bare command scoped to the authenticated user's own work. `SearchUsers`
does not inject anything because GitHub user search ignores those qualifiers.

### Team-to-repo Resolution

There is no `team:` qualifier in GitHub search. `--team` must be the
self-contained `ORG/SLUG` form; `--org` remains a search qualifier and
does not provide the organization for a bare team slug. CLI parsing turns
team values into `TeamScope(org, slug)` objects, then the use case calls
`GET /orgs/{org}/teams/{slug}/repos` and expands the result into the same
parenthesized OR repo group used by explicit repeated `--repo` flags. The
use case bounds each team at `MAX_TEAM_REPO_QUALIFIERS + 1` with
`itertools.islice`; if the cap is exceeded, keep the first N and emit a
stderr warning through the injected `warn` callback. Keep the cap
conservative: the generated OR group expands quickly under GitHub's search
query length budget, and users can pass explicit `--repo` scopes when they
intentionally want a wider query.

`--repo-stdin` reads repo scopes with the SDK's
`read_identifiers([], stdin=True, id_field="full_name")` and appends them to
explicit `--repo` values before the filter object is constructed. It accepts
either bare newline-separated `owner/name` lines **or** an untaped `--format
pipe` stream (each record's `full_name` is extracted), so `untaped-github search
repos --format pipe | untaped-github search code --repo-stdin` composes. Only
`github.repo` records carry `full_name`, so only a `search repos` pipe feeds
`--repo-stdin`; piping `code`/`issue`/`user` output into it fails loud with a
line-precise error. The search commands and `whoami`
tag their output via `render_rows(..., kind="github.<repo|code|issue|user>")`.
Keep this in the CLI
layer: application use cases should receive already-parsed `repos` and
`TeamScope` values, not own stdin.

### Pagination

`paginate_search` and `paginate_list` follow GitHub RFC 5988 `Link` headers
until exhausted or `--limit` is hit. Search payloads nest rows under `items`;
list payloads, such as team repos, return JSON arrays.

`pagination.py` keeps only the GitHub knowledge — `Link`-header parsing and
the payload shapes — as a fetch closure handed to the SDK's `paginate_pages`,
which owns the loop, the limit, the cursor-cycle guard, and the
100-page non-convergence cap (`UntapedError`).

Two efficiency/defense rules are load-bearing:

- When `--limit < per_page`, the first request asks only for `limit` rows.
- `paginate_pages` caps the walk at 100 pages and refuses to follow a
  `next` link that matches any previously followed URL.

## Layering

- `domain/`: `GithubUser`, `RepoResult`, `CodeResult`, `IssueResult`,
  `UserResult`, and frozen filter value objects in `queries.py`. Query
  objects render GitHub `q=` strings and do no I/O.
- `application/`: `WhoAmI`, `SearchRepos`, `SearchCode`, `SearchIssues`,
  `SearchUsers`, and their `Protocol` ports. Scope defaulting and
  team-to-repo resolution live here.
- `infrastructure/`: `GithubClient` (wired via the SDK's `connected_client`),
  `pagination.py` (REST Link-header mechanics over the SDK's `paginate_pages`),
  and `graphql.py` (batched ref-probe query building and response
  parsing). Adapters satisfy application ports structurally and do not
  import `application`.
- `cli/`: composition root. `cli/_client.open_client` reads this tool's config
  and returns a context-managed `GithubClient`; top-level commands use it.

## Development Workflow

```bash
uv sync
uv run pre-commit install
uv run pytest
uv run mypy
uv run ruff check --fix
uv run ruff format
uv run untaped-github --help
```

Use `pytest --no-cov` for tight local loops. Full `pytest` enforces the
coverage gate.

## Recipe: Add A GitHub Subcommand

1. Write a use-case test with a stub satisfying the narrowest port.
2. Add or narrow a port in `application/ports.py` if the command needs new
   service behavior.
3. Add a domain model or query value object in `domain/` when needed.
4. Add the HTTP method to `infrastructure/github_client.py` and keep
   pagination details in `infrastructure/pagination.py` (REST) or query
   building/response parsing in `infrastructure/graphql.py` (GraphQL).
5. Wire the Cyclopts command in `cli/commands.py` or `cli/search_commands.py`;
   keep stdout data-only and expose `--format`/`--columns` for data output.
6. If the command emits rows, update `tests/unit/test_format_raw_first_key.py`.
7. Run `uv run untaped-github <command> --help` plus the full verification
   commands above.

## See Also

- [`untaped` SDK](https://github.com/alexisbeaulieu97/untaped) - CLI
  launcher, settings registry, config-file helpers, output helpers.
- [`untaped` configuration docs](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/configuration.md)
  - user-facing profile, config, secrets, and TLS behavior.
