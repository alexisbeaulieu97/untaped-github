---
name: untaped-github
description: Use the untaped-github CLI.
---

# untaped-github

Use this skill when the user wants an agent to operate the `untaped-github` CLI for authenticated GitHub user, repository inventory, and search workflows.

## Setup

- `untaped-github` is a standalone CLI built on the untaped SDK. Install it with `uv tool install git+https://github.com/alexisbeaulieu97/untaped-github.git`.
- Settings live under `profiles.<name>.github`: `base_url` and `token`.
- `base_url` defaults to `https://api.github.com`; GitHub Enterprise Server usually uses `https://HOST/api/v3`.
- Set the token with `untaped-github config set token --prompt` or `--stdin` (a bare key addresses this tool's own section).
- Set the base URL with `untaped-github config set base_url https://HOST/api/v3`.

## Command Patterns

- `untaped-github whoami` verifies the authenticated token and returns the current user — a single entity, so it renders as a vertical detail view under `--format table` and a bare JSON object (`{…}`) under `--format json`.
- `untaped-github repos list [PATTERN] [--org ORG]... [--team ORG/SLUG|SLUG]...` lists complete org/team repository inventory from GitHub list APIs with at least one repeatable scope.
- `untaped-github search repos` searches repositories.
- `untaped-github search code` searches code and does not support sort.
- `untaped-github search issues` searches issues and pull requests.
- `untaped-github search users` searches users and organizations.
- Search commands support scoped selectors such as `--user`, repeatable `--org`, repeatable `--repo`, and repeatable `--team ORG/SLUG` where applicable.
- Prefer `--team ORG/SLUG` for team-only operations. A bare `--team SLUG` is accepted only when exactly one `--org` is present and normalizes to `ORG/SLUG`.
- `repos list` requires explicit `--org` or `--team` scopes; it does not default to the authenticated user's repositories.
- `repos list` treats `--org` and `--team` as additive scopes: `--team acme/backend` is team-only, while `--org acme --team backend` includes the whole org plus that team.
- In `repos list`, `PATTERN` is a case-insensitive whole-target glob by default; `--regex` switches it to a case-insensitive, unanchored regex substring match. Patterns with `/` match `full_name`, otherwise they match repo `name`.
- Use `repos list --no-archived --no-fork --format raw --columns ssh_url` to produce cloneable URL lines for `untaped-workspace add --stdin`.

## Client API Notes

- `untaped_github` exports `GithubClient`, `GithubSettings`, `GithubGraphqlError`, the ref-probe result models, and the public repository inventory helpers (`RepositoryInventoryScope`, `RepositoryInventoryItem`, `ResolveRepositoryInventory`, `TeamScope`, `normalize_team_scopes`) for sibling untaped tools.
- `GithubClient.batch_repo_refs(...)` treats exact path-scoped GraphQL `NOT_FOUND`/`FORBIDDEN` errors (`path: ["rX"]`) as per-repo missing results. Nested paths raise `GithubGraphqlError`. Global `/graphql` access failures such as HTTP `401`/`403`/`429` or unscoped `RATE_LIMITED` raise `GithubGraphqlError`, which subclasses `UntapedError` and has a user-ready message. Retryable GraphQL HTTP 5xx and transport failures are retried, adaptively split after retry exhaustion, and surfaced as `BatchRepoRefsResult.failures` per repo instead of aborting successful subchunks; this also applies to all-ref pagination follow-up failures. `BatchRepoRefsResult.rate_limit_cost` sums GraphQL `rateLimit.cost` across every POST in the operation; `rate_limit_remaining` and `rate_limit_reset_at` come from the latest response.
- `GithubClient.batch_default_branch_refs(...)` probes only `defaultBranchRef { name target { oid } }` with no `refs(...)` connection and returns the same `BatchRepoRefsResult` shape with one synthesized `heads` ref per repo when a default branch exists. Both default-branch and all-ref probe modes share the same bounded retry and adaptive split machinery for transient GraphQL failures.
- Known limitation: a `200 OK` response containing per-alias `FORBIDDEN` for every repo is still reported as per-repo missing/inaccessible rather than inferred as a global SSO or token-scope failure.

## Agent Guidance

- Prefer `--format json` for structured search results.
- Prefer `repos list` over `search repos` when the user needs complete org/team inventory or local glob/regex matching.
- Use `--format pipe` to chain a search into another untaped tool: each
  record is tagged (`github.repo`/`github.code`/...), and `--repo-stdin` reads a
  `--format pipe` stream back (mapping `full_name`) as well as bare `owner/name`
  lines — e.g. `untaped-github search repos --org acme --format pipe |
  untaped-github search code "BaseModel" --repo-stdin`.
- For `untaped-workspace add --stdin`, use raw URL lines:
  `untaped-github repos list 'play*' --team acme/backend --format raw --columns ssh_url |
  untaped-workspace add --stdin --workspace prod`. `repos list --format pipe`
  emits `github.repo` records, but workspace add does not consume typed pipe records today.
- `--profile <name>` works in any token position (e.g. `untaped-github --profile work whoami`).
- Use `--limit` intentionally; GitHub search has stricter rate limits than normal REST reads.
- When no repo/org/user/team scope is passed to repo/code/issue search, the CLI defaults to the authenticated user.
- Repeated repo scopes are ORed together; do not rewrite them as separate AND qualifiers.
- `search repos` automatically batches large team-expanded repo scopes around
  GitHub's search validation limits: at most five `AND`/`OR`/`NOT` operators
  and 256 user query-text characters per request. With no user boolean
  operators, each generated repo batch contains at most six repos; user
  boolean operators reduce that budget. Results are deduped by `full_name`;
  best-match and `help-wanted-issues` stop once `--limit` unique rows are
  available, while `stars`, `forks`, and `updated` query all batches and
  locally merge-sort before the final limit.
