# AGENTS.md - `untaped-github`

Single source of truth for this standalone CLI repo. If you change
architecture, command behavior, settings behavior, or the development
workflow, update this file in the same commit.

## Mission

`untaped-github` is a standalone CLI built on the `untaped` SDK, invoked as
`untaped-github`. It provides authenticated user inspection, GitHub REST
search (`repos`, `code`, `issues`, `users`), complete org/team repository
inventory, and local Git-corpus scans for repeated team-wide code searches.
The `untaped` SDK owns config
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
    `login`; repo search and repo-list rows start with `full_name`; issue
    search rows start with `repo`; user search rows start with `id`; code
    search rows start with `name`.
11. **Human table output honors profile UI settings.** GitHub row commands
    render `--format table` through the active settings-backed
    `ui_context().collection(...)` so per-profile themes and
    `ui.collection_view` apply.
12. **Structured output bypasses configured themes.** `--format json`, `yaml`,
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
└── infrastructure/       # GithubClient, REST/GraphQL adapters, Git corpus
```

The CLI declares `GithubSettings` as its `github` settings section, mounts
the Cyclopts `app` as the root command, and ships the packaged
`untaped-github` agent skill. Keep that static skill asset current with major
GitHub workflow changes. Command code reads typed settings with
`app_context().section("github", GithubSettings)`, not a global
aggregate `settings.github` attribute.

## Auth Model

GitHub uses bearer-token auth. The token is a `SecretStr` read through
`app_context().section("github", GithubSettings)` or
`UNTAPED_GITHUB__TOKEN`. The CLI composition root reads it once and passes
the narrowed `GithubSettings` into `GithubClient`. Adapters never read the
full SDK settings aggregate directly.

Profile selection is owned by the SDK: the `--profile` option works in any
token position, so commands define no command-local `--profile` parameter.
Commands call bare `open_client()`, which calls `app_context()`; the SDK
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

`github.corpus_path` defaults to `~/.untaped/github-corpus` and is owned by
the `scan` command group. It stores managed bare repositories and worktrees
used for local scans; do not treat it as a human development workspace.

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

`untaped_github` intentionally re-exports `GithubClient`,
`GithubSettings`, and `GithubGraphqlError` for sibling untaped tools that
need GitHub access, plus the ref-probe result models
(`BatchRepoRefsResult`, `BatchRepoRefsFailure`, `RepoRefs`, `RepoRef`)
and reusable inventory helpers (`RepositoryInventoryScope`,
`RepositoryInventoryItem`, `ResolveRepositoryInventory`, `TeamScope`,
`normalize_team_scopes`).
Keep this surface small and tested. Library consumers may use repository
metadata, org/team repository inventory expansion, matching refs, batched
ref probing, tree reads, and raw content reads. Add missing GitHub
operations here rather than duplicating a GitHub client in another tool
or importing private CLI helpers.

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
  per-repo point cost. `GithubClient.batch_default_branch_refs(...)`
  uses `defaultBranchRef { name target { oid } }` with no `refs(...)`
  connection and returns the same `BatchRepoRefsResult` shape with one
  synthesized `heads` ref per repo when a default branch exists.
- **Missing repos don't raise.** A `null` data node plus a `NOT_FOUND`
  or `FORBIDDEN` error with exact `path: ["rX"]` lands the input full
  name in `BatchRepoRefsResult.missing`; nested paths raise
  `GithubGraphqlError`.
- **Transient probe failures are per-repo results.** Retryable GraphQL
  HTTP 5xx responses and transport failures are retried on the same
  chunk, then adaptively split only after retry exhaustion. Successful
  subchunks are preserved; isolated transient repo failures land in
  `BatchRepoRefsResult.failures` as `BatchRepoRefsFailure` rows. If both
  halves fail without any success, the split recurses one additional
  generation before reporting the remaining subchunks as transient
  failures to avoid unbounded GitHub outage amplification.
- **Global GraphQL access failures raise `GithubGraphqlError`.** HTTP
  `401`, `403`, and `429` responses from `/graphql`, plus unscoped
  GraphQL errors such as `RATE_LIMITED`, are classified as
  `kind="auth"`, `"forbidden"`, `"rate_limited"`,
  `"secondary_rate_limited"`, or `"unknown"`. The exception subclasses
  the SDK's `UntapedError`, carries the status/url/body snippet when
  available, and its string is user-ready for SDK CLI error reporting.
  Known limitation: if GitHub returns `200 OK` with per-alias
  `FORBIDDEN` for every repo, v1 still reports those repos as
  missing/inaccessible rather than inferring a global SSO or token-scope
  failure.
- **Ref-pagination overflow** (>100 refs in a namespace) is followed
  serially with single-repo `after: <cursor>` queries until exhausted.
  Exhausted transient HTTP 5xx or transport failures during pagination
  become one `BatchRepoRefsFailure` for that repo; repo-lost errors still
  raise because they are not transient.
- **Adaptive 5xx behavior applies to both probe modes.** All-ref probes
  and connection-free default-branch probes share the same bounded retry
  and adaptive split machinery.

GraphQL has its own 5000 points/hour budget (separate from REST), at
roughly one point per repo per ref connection. A full heads+tags probe
of 1500 repos costs ≈ 3000 points — callers should watch
`BatchRepoRefsResult.rate_limit_cost`,
`BatchRepoRefsResult.rate_limit_remaining`, and
`BatchRepoRefsResult.rate_limit_reset_at` from GraphQL `rateLimit`.
`rate_limit_cost` is summed across every POST in the probe operation;
`remaining` and `reset_at` come from the latest response. Callers should
warn or stop when the budget runs low.

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

## Local Scan Corpus

`scan` is a Cyclopts sub-app for local, repeatable code scans. It is not a
GitHub Search wrapper and must not call `/search/*`.

- `scan sync` expands inventory scopes through `ResolveRepositoryInventory`
  and fetches each repo's current default branch into a deterministic bare
  repo under `github.corpus_path`.
- `scan grep` expands scopes with REST inventory, then runs local `git grep`
  against cached default branches. It uses cache-as-is unless `--sync` is
  passed. `git grep` exit `1` is a successful no-match, not a failure.
  Binary files are skipped with `git grep -I`.
- `scan worktree` materializes one cached repo/ref for editor or manual `rg`
  workflows. It resolves repository metadata from the local corpus instead of
  live REST inventory; `--ref` only works for refs already cached locally. Bulk
  human workspaces belong to `untaped-workspace`.
- `scan list` and `scan clean` inspect/prune the managed corpus. Clean
  operations require `--repo` or `--all --yes`, remove managed worktrees before
  deleting a bare repo, and must refuse paths outside the managed root. List
  skips corrupt metadata entries with a warning instead of hiding healthy rows.

The corpus fetch is shallow and blobful by default. Do not add
`--filter=blob:none` to scan fetches: `git grep <ref>` needs blobs present
locally. V1 sync is default-branch-only and authenticated Git transport is
HTTPS-token-backed. SSH, all-ref scans, and `untaped-ansible` adoption require
separate designs.

## Repository Inventory

`repos list` is a Cyclopts sub-app mounted on the root `github` app for
complete repository inventory from REST list endpoints, not GitHub search.
It requires at least one explicit scope: repeatable `--org ORG` and/or
repeatable `--team ORG/SLUG`. A bare `--team SLUG` is accepted only when
exactly one `--org` is present and normalizes to `ORG/SLUG`. There is
intentionally no bare `@me` default or `--user` scope in v1; user-owned
inventory would require a separate `/user/repos` design.

Inventory scopes are additive. `--team acme/backend` by itself lists only
that team's repositories; `--org acme --team backend` lists the whole
`acme` org plus the `acme/backend` team, with duplicate repos deduped by
`full_name`.

`repos list [PATTERN]` filters locally after fully paginating the selected
scopes. `PATTERN` is a case-insensitive whole-target glob by default;
`--regex` treats it as a case-insensitive, unanchored regular expression
substring match; use `^...$` to anchor it. A pattern containing `/` matches
`full_name`; otherwise it matches the repository leaf `name`. The command
also supports local `--archived/--no-archived` and `--fork/--no-fork`
filters. After filtering, rows are deduped by `full_name` and sorted
case-insensitively by `full_name`.

The list endpoints are walked to completion before local filters run. This is
intentional v1 behavior: correctness and complete inventory win over reducing
page count. GitHub-side list parameters, caching, and a debugging limit are
future work.

Repo-list rows use a dedicated `RepoListResult` model so adding inventory
fields does not change `search repos` output. The first field stays
`full_name`; common pipe columns include `ssh_url`, `clone_url`,
`default_branch`, `private`, `archived`, and `fork`. Both `search repos`
and `repos list` emit `github.repo` pipe records, but their field sets are
not identical; consumers should key on `full_name` or request explicit
columns.

`repos list --format pipe` is tagged as `kind="github.repo"` for consistency
with other repo row producers. `untaped-workspace add --stdin` does not
consume typed pipe records today because it reads bare URL identifiers
without an `id_field`; the supported workspace pipeline is raw URL lines:

```bash
untaped-github repos list 'play*' --team acme/backend --no-archived --no-fork \
  --format raw --columns ssh_url \
  | untaped-workspace add --stdin --workspace prod
```

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
`--team ORG/SLUG` (repeatable), or bare `--team SLUG` when exactly one
`--org` is present. `search users` does not; GitHub's user-search endpoint
ignores those qualifiers, so exposing them would mislead. All search commands
share `--limit` and the SDK's `--format/-f` + `--columns/-c`.

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

There is no `team:` qualifier in GitHub search. `--team` is self-contained
as `ORG/SLUG` unless exactly one `--org` is present, in which case a bare
team slug normalizes to that org. CLI parsing turns team values into
`TeamScope(org, slug)` objects, then the use case calls
`GET /orgs/{org}/teams/{slug}/repos` and expands the result into the same
parenthesized OR repo group used by explicit repeated `--repo` flags. The
repository-search use case resolves team repositories to completion and
dedupes them with explicit `--repo` scopes, preserving first-seen order. It
then splits the repo scopes into multiple `/search/repositories` calls using
GitHub's search validation constraints: at most five boolean operators per
query and at most 256 user query-text characters, excluding generated
qualifiers/operators and unquoted supported raw qualifiers. Quoted terms
always count as literal query text, so quoted `AND`/`OR`/`NOT` tokens do not
reduce the generated repo batch budget. With no user-supplied boolean
operators this means up to six generated repo qualifiers per batch;
user-supplied unquoted `AND`/`OR`/`NOT` tokens reduce that budget, and more
than five user boolean operators fail before any HTTP request.

Repository-search rows are deduped by `full_name`. For the default best-match
order and `--sort help-wanted-issues`, the use case stops querying batches as
soon as it has enough unique rows for `--limit`, so selection is still
batch-order dependent. Multi-batch `--sort help-wanted-issues` searches emit
a warning because GitHub applies that sort per request. For `--sort stars`,
`--sort forks`, and `--sort updated`, every batch is queried and results are
locally merge-sorted before the final `--limit` slice; ties sort by
`full_name`.

`search code` and `search issues` still use the conservative
`MAX_TEAM_REPO_QUALIFIERS` per-team cap and warning behavior. Do not reuse the
repository-search batching behavior for those endpoints without endpoint-
specific tests for ordering, limits, and GitHub validation behavior.

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

- `domain/`: `GithubUser`, `RepoResult`, `RepoListResult`, `CodeResult`,
  `CodeHitResult`, `CorpusRepoResult`, `IssueResult`, `UserResult`, frozen
  search filter value objects in `queries.py`, local corpus value objects in
  `corpus.py`, and pure repo inventory pattern helpers in `repo_filters.py`.
  Query/filter helpers do no I/O.
- `application/`: `WhoAmI`, `SearchRepos`, `SearchCode`, `SearchIssues`,
  `SearchUsers`, `ListRepos`, `SyncCorpus`, `GrepCorpus`, `ListCorpus`,
  `CleanCorpus`, `WorktreeCorpus`, shared scope value objects, and their
  `Protocol` ports. Scope defaulting, team-to-repo resolution, repo-list
  enumeration, dedupe, ordering, and corpus orchestration live here.
- `infrastructure/`: `GithubClient` (wired via the SDK's `connected_client`),
  `pagination.py` (REST Link-header mechanics over the SDK's `paginate_pages`),
  `graphql.py` (batched ref-probe query building and response parsing), and
  `git_corpus.py` (local Git subprocess adapter). Adapters satisfy application
  ports structurally and do not import `application`.
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
5. Wire the Cyclopts command in `cli/commands.py`, `cli/search_commands.py`,
   or another focused sub-app module; keep stdout data-only and expose
   `--format`/`--columns` for data output.
6. If the command emits rows, update `tests/unit/test_format_raw_first_key.py`.
7. Run `uv run untaped-github <command> --help` plus the full verification
   commands above.

## See Also

- [`untaped` SDK](https://github.com/alexisbeaulieu97/untaped) - CLI
  launcher, settings registry, config-file helpers, output helpers.
- [`untaped` configuration docs](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/configuration.md)
  - user-facing profile, config, secrets, and TLS behavior.
