# AGENTS.md - `untaped-github`

GitHub-specific companion to the suite-wide SDK guide and fleet conventions:
[`docs/plugins.md`](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/plugins.md)
and
[`docs/tool-conventions.md`](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/tool-conventions.md).
This file keeps only `untaped-github` rules, contracts, and gotchas.

## Mission

`untaped-github` is a standalone CLI built on the `untaped` SDK, invoked as
`untaped-github`. It provides authenticated user inspection, GitHub REST
search (`repos`, `code`, `issues`, `users`), complete org/team repository
inventory, and question-first `sweep` workflows for repeated team-wide code
and file-presence checks over a managed local Git corpus.
The `untaped` SDK owns shared config, output, HTTP/TLS, profile, and error
machinery.

## Hard Rules

1. **Keep `AGENTS.md` and the packaged skill up to date.** Architecture
   changes, new command patterns, settings changes, and major GitHub
   workflow changes must be documented here and in
   `src/untaped_github/skills/untaped-github/SKILL.md`.
2. **Keep the GitHub `ToolSpec` particulars stable.** The console script is
   `untaped_github.__main__:main`; `ToolSpec` declares
   `command="untaped-github"`, `section="github"`,
   `profile_model=GithubSettings`, and one packaged skill named
   `untaped-github`. The root package re-exports `app` lazily via PEP 562
   `__getattr__` so importing `untaped_github` does not import the command tree.
3. **Keep GitHub row identifiers and pipe kinds stable.** `GithubUser` starts
   with `login`; repo search and repo-list rows start with `full_name` and emit
   `github.repo`; issue search rows start with `repo` and emit `github.issue`;
   user search rows start with `id` and emit `github.user`; code search rows
   start with `name` and emit `github.code`; sweep repo rows start with
   `full_name` and emit `github.sweep_repo`; sweep match rows start with
   `full_name` and emit `github.sweep_match`; corpus/worktree rows start with
   `repo` and emit `github.corpus_repo` / `github.worktree`.
4. **Secrets stay secret.** `GithubSettings.token` is a `SecretStr`; call
   `.get_secret_value()` only inside the HTTP adapter.
5. **Build GitHub HTTP clients with `connected_client(...)`.** GitHub clients
   must use the `github` section, bearer-token auth, the configured base URL,
   and the SDK-resolved TLS policy; never hard-code TLS verification policy.

## Release Workflow

`untaped-github` publishes to TestPyPI and PyPI from
`.github/workflows/release.yml`. The workflow is manual-only, uses Trusted
Publishing through `pypa/gh-action-pypi-publish`, and creates the GitHub
release/tag only after a production PyPI publish and published-package smoke
pass. Do not dispatch the workflow, create tags/releases, merge release PRs,
or change PyPI/GitHub environments without explicit approval for that exact
action.

Development and CI resolve `untaped` from PyPI; the repo keeps no standing
git source pin. Release artifacts are built with `uv build --no-sources`, so
published metadata comes from the dependency range. When changing the SDK
floor, update the dependency range and `uv.lock` together so
`uv sync --frozen` remains satisfiable.

The release helper reads internal `untaped*` dependency floors from
`pyproject.toml` and verifies they resolve from the selected index before
publishing. Do not duplicate those floors in workflow YAML.

If a package upload succeeds but a later smoke or GitHub release step fails,
the version is burned on that index. Do not rerun the same version workflow;
recover only the missing side effect when appropriate, then fix the workflow
or bump the patch version for another upload.

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

Commands call bare `open_client()`, which pulls the `github` section and SDK
HTTP settings from `app_context()`.

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
the `sweep` and `cache` command groups. It stores managed bare repositories
and worktrees used for local sweeps; do not treat it as a human development
workspace. `github.sweep.max_age_seconds` defaults to `3600`, and
`github.sweep.sync_concurrency` defaults to `12` before the existing SDK
parallel clamp is applied.

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

## Sweep and Cache Corpus

`sweep` is the primary local Git-corpus workflow. It is question-first:
scope plus refs plus predicates produce either matching repository rows or
deduped match rows. It is not a GitHub Search wrapper and must not call
`/search/*`; online sweeps use REST inventory only to resolve scopes, then
fetch and evaluate locally with `git`.

- `sweep` requires at least one scope (`--org`, `--team`, `--repo`, or
  `--stdin`) and at least one predicate (`--grep`, `--not-grep`,
  `--has-file`, or `--lacks-file`). `--path` only scopes content predicates;
  by itself it is a usage error that should point users at `--has-file`.
- Content predicates run through `git grep -I` so binary files are skipped.
  `--ignore-case`/`-i`, `--fixed-strings`/`-F`, and `--word-regexp`/`-w`
  apply to every content predicate in the query. Positive predicates combine
  with AND by default, `--any` ORs positive predicates only, and negated
  predicates always remain conjunctive. Predicate labels stay
  `grep:<pattern>`, `not-grep:<pattern>`, `has-file:<glob>`, and
  `lacks-file:<glob>`.
- Up-front validation uses a scratch `git grep` call for each content pattern
  with all `--path` pathspecs attached, so bad regexes and bad pathspecs fail
  before any sync work. `--has-file`, `--lacks-file`, and `--ref` globs are
  evaluated in-process and are not pre-validated.
- Fetches are shallow and blobful by default; do not add
  `--filter=blob:none` because `git grep <ref>` needs blobs present locally.
  Fetch profiles are `default`, `branches`, `tags`, and `all`, with additional
  `--ref` globs unioned in. Corpus metadata records the fetched profile,
  ref globs, clone URL, and archived bit; profiles only widen and never
  narrow.
- Online sweeps refresh uncached, stale, or under-profiled repos, with staleness
  controlled by `github.sweep.max_age_seconds`. `--sync` forces a refresh;
  `--no-sync` scans only what metadata says is available on disk. If refresh
  fails but the cached copy already covers the requested refs, the repo is
  scanned from cache and counted as cached; if there is no usable covering copy,
  it lands in the unscanned bucket. The footer reports matched/scanned counts,
  refreshed/cached counts, oldest fetched timestamp, and unscanned warnings.
- Exit code `1` is promoted only by `--strict` with any unscanned repo or by
  `--fail-on-match` with any matching repo. Ordinary no-match, match, or
  non-strict unscanned sweeps exit `0` after reporting the footer.
- `github.sweep_repo` records contain `full_name`, `clone_url`,
  `refs_matched`, `hits`, `owners`, and `synced_at`. `github.sweep_match`
  records contain `full_name`, `refs`, `path`, `line`, and `text`; one deduped
  match can list multiple refs when the same blob is reachable from more than
  one selected ref.
- `cache status`, `cache clean`, and `cache worktree` are the lifecycle group.
  `cache status` emits `github.corpus_repo` rows with profile, freshness, and
  disk size. `cache clean` requires exactly one of `--repo`, `--all`, or
  `--prune`; all destructive paths use `batch_apply` and prompt unless
  `--yes`/`-y` is passed. `--prune` resolves live inventory for `--org` scopes
  and removes cached repos that departed or are now archived. It rejects
  `--team` because team membership is not recorded in corpus metadata, so
  "departed from this team" is not locally decidable.
  `cache worktree` materializes one cached repo/ref and emits `github.worktree`.

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

`--repo-stdin` accepts bare newline-separated `owner/name` lines or
`github.repo` pipe records, extracting `full_name` before the filter object is
constructed. That makes
`untaped-github search repos --format pipe | untaped-github search code --repo-stdin`
compose. Piping `github.code`/`github.issue`/`github.user` output into
`--repo-stdin` fails loud with a line-precise error. Keep this in the CLI layer:
application use cases should receive already-parsed `repos` and `TeamScope`
values, not own stdin.

### Pagination

`paginate_search` and `paginate_list` follow GitHub RFC 5988 `Link` headers
until exhausted or `--limit` is hit. Search payloads nest rows under `items`;
list payloads, such as team repos, return JSON arrays.

`pagination.py` keeps only the GitHub knowledge — search payloads unwrap
`items`, list payloads are raw arrays, and GitHub uses `per_page` — as thin
wrappers around the SDK's `paginate_link`, which owns Link parsing, limits,
the cursor-cycle guard, and the 100-page non-convergence cap.

Two efficiency/defense rules are load-bearing:

- When `--limit < per_page`, the first request asks only for `limit` rows.
- `paginate_link` caps the walk at 100 pages and refuses to follow a
  `next` link that matches any previously followed URL.

## Layering

- `domain/`: `GithubUser`, `RepoResult`, `RepoListResult`, `CodeResult`,
  `CodeHitResult`, `CorpusRepoResult`, `IssueResult`, `UserResult`, frozen
  search filter value objects in `queries.py`, local corpus value objects in
  `corpus.py`, and pure repo inventory pattern helpers in `repo_filters.py`.
  Query/filter helpers do no I/O.
- `application/`: `WhoAmI`, `SearchRepos`, `SearchCode`, `SearchIssues`,
  `SearchUsers`, `ListRepos`, `Sweep`, `StatusCorpus`, `CleanCorpus`,
  `WorktreeCorpus`, and shared scope value objects. Scope defaulting,
  team-to-repo resolution, repo-list enumeration, dedupe, ordering, sweep
  orchestration, and corpus lifecycle orchestration live here.
- `infrastructure/`: `GithubClient` (wired via the SDK's `connected_client`),
  `pagination.py` (GitHub search/list wrappers over the SDK's `paginate_link`),
  `graphql.py` (batched ref-probe query building and response parsing), and
  `git_corpus.py` (local Git subprocess adapter).
- `cli/`: composition root. `cli/_client.open_client` reads this tool's config
  and returns a context-managed `GithubClient`; top-level commands use it.

## Recipe: Add A GitHub Subcommand

1. Write a use-case test with a GitHub service stub.
2. Add a domain model or query value object in `domain/` when needed.
3. Add the HTTP method to `infrastructure/github_client.py` and keep
   pagination details in `infrastructure/pagination.py` (REST) or query
   building/response parsing in `infrastructure/graphql.py` (GraphQL).
4. Wire the command in `cli/commands.py`, `cli/search_commands.py`, or another
   focused sub-app module.
5. If the command emits rows, update the GitHub identifier/kind contracts in
   tests and this file.
6. Run `uv run untaped-github <command> --help` plus the fleet verification
   loop from `docs/tool-conventions.md`.

## See Also

- [`untaped` SDK](https://github.com/alexisbeaulieu97/untaped) - CLI
  launcher, settings registry, config-file helpers, output helpers.
- [`untaped` configuration docs](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/configuration.md)
  - user-facing profile, config, secrets, and TLS behavior.
