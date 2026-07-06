# GitHub

`untaped-github` is a standalone CLI, built on the
[`untaped`](https://github.com/alexisbeaulieu97/untaped) SDK, that inspects
the authenticated user, lists complete org/team repository inventory, searches
GitHub for repositories, code, issues/PRs, and users/orgs, and sweeps a local
Git corpus for repeated team-wide code and file-presence checks. Commands that
talk to GitHub authenticate with the token from the tool's `token` setting.
Scoped search commands default to the authenticated user, so bare scoped
searches answer "what's mine?".

## Setup

```bash
uv tool install untaped-github
untaped-github config set token ghp_xxx         # bare key → this tool's section
untaped-github whoami                           # confirm it works
```

Profile selection is built into the SDK: the `--profile <name>` option
works in any token position, e.g. `untaped-github --profile work whoami`.

The token is stored as a secret: `untaped-github config list` shows `***`,
not the value. See the core
[`configuration.md`](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/configuration.md)
for the full config model.

You can also override the API base URL. For GitHub Enterprise Server,
use the API path:

```bash
untaped-github config set base_url https://github.example.com/api/v3
```

The local sweep corpus defaults to `~/.untaped/github-corpus` and can be
changed with:

```bash
untaped-github config set corpus_path ~/.cache/untaped-github/corpus
```

## Commands

### `whoami`

```bash
untaped-github whoami
untaped-github --profile work whoami
untaped-github whoami --format json
untaped-github whoami --format raw --columns login
```

Calls `GET /user` and prints the authenticated user's profile. As a single
entity it renders as a vertical key:value detail view under `--format table`
and as a bare JSON object (`{…}`, not a one-element `[{…}]`) under
`--format json`. It is pipe-friendly for shell prompts and scripts:

```bash
echo "[gh:$(untaped-github whoami --format raw --columns login)]"
```

### `repos list`

`untaped-github repos list` lists complete repository inventory from GitHub
org/team list APIs. It is for "which repositories are in these scopes?"
workflows; use `search repos` for GitHub's indexed repository search.

```bash
untaped-github repos list --org acme
untaped-github repos list 'play*' --team acme/backend
untaped-github repos list 'play*' --org acme --team backend
untaped-github repos list '^acme/play-[0-9]+$' --org acme --regex
```

At least one explicit scope is required. V1 supports repeatable `--org ORG`
and `--team ORG/SLUG`; a bare `--team SLUG` is accepted only when exactly
one `--org` is present, and is normalized to `ORG/SLUG`. It does not list
user-owned repositories with a bare default or `--user`.

`repos list` treats `--org` and `--team` as additive inventory scopes. Use
`--team acme/backend` by itself for team-only inventory; `--org acme --team
backend` lists the whole `acme` org plus the `acme/backend` team, deduped by
`full_name`.

`PATTERN` is optional and is applied locally after the selected scopes are
fully paginated. It is a case-insensitive whole-target glob by default;
pass `--regex` to use a case-insensitive, unanchored regular expression
substring match. Use `^...$` when you want regex matching anchored to the
whole target. A pattern containing `/` matches `full_name` (`owner/name`);
otherwise it matches the repository leaf `name`.

Examples:

```bash
untaped-github repos list api-service --org acme --org beta   # match repo name
untaped-github repos list 'acme/*' --org acme                 # match full_name
untaped-github repos list '*/api-service' --org acme --org beta
```

Local filters:

| Flag                       | Effect                                      |
| -------------------------- | ------------------------------------------- |
| `--org ORG`                | Include all visible repos in an org.        |
| `--team ORG/SLUG` or `SLUG` | Include all visible repos for a team. Bare `SLUG` requires exactly one `--org`. |
| `--archived/--no-archived` | Include or exclude archived repositories.   |
| `--fork/--no-fork`         | Include or exclude forks.                   |
| `--regex`                  | Treat `PATTERN` as an unanchored regex.     |
| `--format`                 | `table` (default), `json`, `yaml`, `raw`, `pipe`. |
| `--columns`                | Repeatable; dotted paths supported.         |

Rows are deduped by `full_name` and sorted by `full_name`. Use `--columns`
to select clone URL fields for shell pipelines:

```bash
untaped-github repos list 'play*' \
  --team org-a/team-a \
  --team org-b/team-b \
  --no-archived \
  --no-fork \
  --format raw --columns ssh_url \
  | untaped-workspace add --stdin --workspace prod
```

The workspace pipeline above deliberately uses `--format raw`: `repos list
--format pipe` emits `github.repo` records, but `untaped-workspace add
--stdin` reads bare URL lines today and does not consume typed pipe records.
`search repos` and `repos list` both emit `github.repo` records, but their
field sets differ; `full_name` is the shared stable identifier.

`repos list` favors complete inventory over API minimization in v1. Local
pattern and boolean filters do not reduce GitHub page count; the command
fetches the selected org/team scopes to exhaustion before filtering. Server
side list parameters, caching, and a debugging limit are deferred.

### `sweep`

`untaped-github sweep` answers "which repositories match this question?" over
a managed local Git corpus. It deliberately avoids GitHub Search APIs for the
code search itself. Online sweeps use REST inventory to expand `--org`,
`--team`, and `--repo`, then fetch and evaluate locally with `git`; Git must be
available on `PATH`.

```bash
untaped-github sweep --org acme --grep 'requests\.get\(' --path 'src/**' --has-file Jenkinsfile
untaped-github sweep --team acme/platform --grep log4j --grep slf4j --any
untaped-github sweep --org acme --grep old_api --not-grep new_api
untaped-github sweep --org acme --ref 'release/*' --grep jenkins --show matches
untaped-github sweep --org acme --grep 'dangerous_call' --fail-on-match
```

Every sweep needs a scope (`--org`, `--team`, `--repo`, or `--stdin`) and at
least one predicate. Content predicates are `--grep PATTERN` and
`--not-grep PATTERN`; file-presence predicates are `--has-file GLOB` and
`--lacks-file GLOB`. `--path PATHSPEC` narrows content predicates and must be
paired with a content predicate. `--ignore-case`/`-i`,
`--fixed-strings`/`-F`, and `--word-regexp`/`-w` apply to every content
predicate in the query.

Positive predicates combine with AND by default. `--any` ORs positive
predicates only; negated predicates always remain conjunctive. Predicate
labels in table and pipe output are stable:
`grep:<pattern>`, `not-grep:<pattern>`, `has-file:<glob>`, and
`lacks-file:<glob>`.

By default, sweeps cover each repository's default branch. `--refs branches`,
`--refs tags`, and `--refs all` widen the cached profile; repeatable
`--ref GLOB` adds matching branch/tag refs to the default branch. Cache
metadata only widens, never narrows, so a later narrow sweep can reuse a wider
cache.

Sync behavior:

| Flag | Effect |
| ---- | ------ |
| default | Refresh uncached, stale, or under-profiled repos before scanning. |
| `--sync` | Force a refresh for every repo in scope. |
| `--no-sync` | Scan only local corpus metadata and cached refs; org/team live expansion is unavailable. |
| `--depth N` | Git fetch depth; `0` is full. Default `1`. |
| `--parallel`/`-j` | Parallel Git workers, capped at 32. |

Freshness uses `github.sweep.max_age_seconds` (default `3600`), and the
worker default is `github.sweep.sync_concurrency` (default `12`). A failed
refresh does not automatically fail the sweep: if the local cache already
covers the requested refs, the repo is scanned from cache and counted as
cached; otherwise it is listed in the unscanned bucket. The footer reports:

```text
Sweep: N matched of M scanned (R refreshed, C cached), oldest fetch <timestamp>
warning: unscanned OWNER/NAME: <reason>
```

Default exit code is `0` for no matches, matches, and non-strict unscanned
gaps. `--fail-on-match` promotes any matching repo to exit `1`, which is the
CI gate for banned patterns. `--strict` promotes any unscanned repo to exit
`1`.

The default `--show repos` output emits `github.sweep_repo` records with:
`full_name`, `clone_url`, `refs_matched`, `hits`, `owners`, and `synced_at`.
Table view shows `full_name`, one column per predicate label, `refs_matched`
when refs go beyond default, and `owners`.

`--show matches` emits `github.sweep_match` records with:
`full_name`, `refs`, `path`, `line`, and `text`. Identical content reachable
from multiple selected refs is deduped into one match row with multiple refs.

Typed sweep records can feed another sweep because `--stdin` reads
`full_name` from pipe envelopes or bare owner/name lines:

```bash
untaped-github repos list 'svc-*' --org acme --format pipe \
  | untaped-github sweep --stdin --grep 'old_api' --format pipe \
  | untaped-github sweep --stdin --not-grep 'new_api'
```

`untaped-workspace add --stdin` reads generic URL lines, not typed pipe
records. Use raw URL output when turning matching repos into a workspace:

```bash
untaped-github sweep --org acme --grep 'old_api' \
  --format raw --columns clone_url \
  | untaped-workspace add --stdin --workspace remediation
```

### `cache`

`untaped-github cache` exposes lifecycle commands for the managed local corpus:

```bash
untaped-github cache status
untaped-github cache clean --repo acme/api --yes
untaped-github cache clean --all --yes
untaped-github cache clean --prune --org acme --yes
untaped-github cache worktree acme/api --format raw --columns path
```

`cache status` emits `github.corpus_repo` rows with repo, ref, path,
clone URL, status, fetched timestamp, fetch profile, ref globs, archived bit,
and recursive disk size. It also prints cache count, total disk bytes, and the
oldest/newest fetched timestamps.

`cache clean` requires exactly one of `--repo`, `--all`, or `--prune`.
Delete operations prompt unless `--yes`/`-y` is passed and remove managed
worktrees before deleting a bare repo. `--prune` accepts `--org`/`--team`,
resolves live inventory, and removes cached repos in scope that departed or
are now archived.

`cache worktree REPO` materializes one cached repo/ref into a managed worktree
and prints its path. Worktree resolution is local-corpus backed and does not
need a REST inventory lookup; `--ref` only works for refs already cached
locally. Bulk human development workspaces remain the job of
`untaped-workspace`; the sweep corpus is optimized for repeated local checks,
not active development.

### `search`

`untaped-github search` exposes one subcommand per GitHub search endpoint.
Every scoped subcommand defaults to `user:@me` when you pass no `--user`,
`--org`, `--repo`, or `--team`.

```bash
untaped-github search repos --language python
untaped-github --profile work search repos --language python
untaped-github search repos --name client --language Go
untaped-github search repos --org acme --visibility private
untaped-github search repos --team acme/backend
untaped-github search code "TODO" --language python
untaped-github search issues --state open --label bug --kind pr
untaped-github search users --kind org --location montreal
```

Common flags for `repos`, `code`, and `issues`:

| Flag          | Effect                                                               |
| ------------- | -------------------------------------------------------------------- |
| `--user`      | `user:<login>` qualifier; pass `@me` to be explicit.                 |
| `--org`       | `org:<name>` qualifier; repeatable.                                  |
| `--repo`      | `repo:owner/name`; repeated values render as an OR scope group.       |
| `--repo-stdin`| Read `owner/name` repo scopes from stdin and append to `--repo`.      |
| `--team ORG/SLUG` or `SLUG` | Resolves the team's repos into an OR repo scope; bare `SLUG` requires exactly one `--org`. |
| `--limit N`   | Stop after N rows. Default `30`; GitHub search caps at 1000 rows.    |
| `--format`    | `table` (default), `json`, `yaml`, `raw`, `pipe`.                    |
| `--columns`   | Repeatable; dotted paths supported.                                  |

`--team` is self-contained as `ORG/SLUG` unless exactly one `--org` is
present, in which case a bare team slug is normalized to that org. `--org`
also remains a search qualifier, so `--org acme --team backend` searches
within the repos resolved from `acme/backend` under the `org:acme` qualifier.

For `search repos`, team-resolved and explicit repo scopes are deduped and
automatically split across multiple `/search/repositories` requests to stay
within GitHub's search validation limits: at most five `AND`/`OR`/`NOT`
operators per query and at most 256 user query-text characters, excluding
generated qualifiers/operators and unquoted supported raw qualifiers. Quoted
terms always count as literal query text, so quoted `AND`/`OR`/`NOT` tokens do
not reduce the repo batch budget. With no user boolean operators, each
generated repo batch contains at most six repos; user boolean operators reduce
that repo budget.

The final rows are deduped by `full_name`. Default best-match searches and
`--sort help-wanted-issues` stop once enough unique rows are available for
`--limit`, so selection remains batch-order dependent. Multi-batch
`--sort help-wanted-issues` searches emit a warning because GitHub applies
that sort per request. `--sort stars`, `--sort forks`, and `--sort updated`
query every batch and locally merge-sort the combined results before applying
the final `--limit`.

Repository-specific: `--name`, `--language`, `--archived/--no-archived`,
`--fork/--no-fork`, `--visibility public|private`,
`--sort stars|forks|help-wanted-issues|updated`.

Code-specific: `--language`, `--filename`, `--path`, `--extension`.

Issue-specific: `--state open|closed`, `--kind issue|pr`, `--author`,
`--assignee`, `--label` (repeatable), `--mentions`.

User-specific: `--kind user|org`, `--location`, `--language`,
`--sort followers|repositories|joined`. User search ignores scope flags
because GitHub does not support them on that endpoint.

A free-text query goes as the first positional argument and is passed to
GitHub's `q=` parameter:

```bash
untaped-github search code "func init" --language go
untaped-github search issues "memory leak" --state open
```

## Pipe-Friendly Examples

```bash
untaped-github search repos --language python --format raw

untaped-github search repos --org acme --format raw \
  | untaped-github search code "TODO" --repo-stdin --format raw --columns repo --columns path

untaped-github search repos --org acme --format raw \
  | untaped-github search issues --state open --repo-stdin \
      --format raw --columns repo --columns number --columns title
```

## See Also

- [`untaped` configuration docs](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/configuration.md)
  for profiles, secrets, and TLS.
- [AGENTS.md](../AGENTS.md) for development rules.
