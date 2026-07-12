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
untaped-github config set sweep.fetch_depth 1
untaped-github config set sweep.sync_concurrency 12
untaped-github config set sweep.max_age_seconds 3600
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
untaped-github sweep content 'requests\.get\(' --org acme
untaped-github sweep content old_api --org acme --without-content new_api
untaped-github sweep content TODO --team acme/platform \
  --include-path 'src/**' --exclude-path 'src/vendor/**' --context 2
untaped-github sweep paths Jenkinsfile --org acme --with-path '.github/**'
untaped-github sweep paths '*.py' --org acme --without-content copyright
untaped-github sweep content dangerous_call --org acme --fail-on-match
```

The target subcommand and required positional value are the primary question
and the only source of reported evidence: `content REGEX` reports content
locations; `paths GLOB` reports tracked paths. Every sweep needs at least one
additive scope (`--org`, `--team`, `--repo`, or `--stdin`). Archived
repositories are excluded unless `--include-archived` is passed.

Repeatable `--with-content`, `--without-content`, `--with-path`, and
`--without-path` constraints are conjunctive. The primary matcher and every
constraint must pass on the same selected ref; constraint witnesses never
appear as report evidence. Pipe records from `repos list` or another sweep are
accepted by `--stdin` through their `full_name` identifier.

Content uses forced POSIX ERE by default, independently of Git configuration.
`--fixed-strings`, `--ignore-case`, and `--word-regexp` apply to every content
matcher in the invocation. Binary files are skipped. `--include-path` and
`--exclude-path` filter content evaluation only, with exclusion winning.

Paths and content filters use case-sensitive gitignore-style patterns. Useful
examples include `Jenkinsfile` (that basename at any depth), `/Jenkinsfile`
(repository root only), `.github/**` (root `.github` descendants), and
`**/*.py`. Negation belongs in the option name: unescaped leading `!`,
comment-only patterns, actual newlines, and invalid content regexes fail before
repository refresh begins.

By default, sweeps cover each repository's default branch. `--refs branches`,
`--refs tags`, and `--refs all` widen the cached profile; repeatable
`--ref GLOB` adds matching branch/tag refs to the default branch. Cache
metadata only widens, never narrows, so a later narrow sweep can reuse a wider
cache while its recorded default-branch identity still matches live inventory.
When the default branch changes, the current request replaces the former
profile and globs, and refs covered only by that former selector are pruned.
Evidence always retains canonical refs such as `refs/heads/main` and
`refs/tags/main`, so same-named branches and tags stay distinct.

Freshness behavior:

| Flag | Effect |
| ---- | ------ |
| default | Refresh uncached, stale, or under-profiled repos before scanning. |
| `--refresh` | Force preparation for every repository in scope. |
| `--cached` | Make no network calls and scan covering corpus state only; rejects `--team`. |

Operational tuning is configuration-only:

```yaml
github:
  sweep:
    fetch_depth: 1
    sync_concurrency: 12
    max_age_seconds: 3600
```

`fetch_depth` and `max_age_seconds` are non-negative; depth `0` requests full
history. `sync_concurrency` is positive and capped by the SDK. A failed refresh
uses a covering cached copy when possible; otherwise the repo becomes a
`prepare` failure. Evaluation errors become `scan` failures.

Every output format writes the coverage summary and unscanned failures to
stderr. Output on stdout is format-specific:

- JSON/YAML serialize the self-contained `{query, results, failures, summary}`
  report. Result projections retain `full_name` and `refs_matched`.
- Table emits one row per primary match with repo, canonical refs, evidence,
  and the result-level owner union.
- Raw emits one row per matching repository. Without columns it emits unique
  `full_name` values; nested match columns are ordered arrays.
- Pipe emits one complete `github.sweep_result` record per result and ignores
  `--columns`, so it remains safe as downstream sweep scope.

For example, `--format json` produces an archival report rather than a bare
row list:

```json
{
  "query": {
    "scope": {"orgs": ["acme"], "teams": [], "repos": [], "stdin": false, "include_archived": false},
    "question": {"kind": "content", "pattern": "TODO"},
    "constraints": [],
    "content_options": {"mode": "extended_regex", "ignore_case": false, "word_regexp": false},
    "path_filters": {"include": [], "exclude": []},
    "refs": {"profile": "default", "globs": []},
    "freshness": "auto",
    "context": 0
  },
  "results": [{
    "full_name": "acme/api",
    "clone_url": "https://github.com/acme/api.git",
    "refs_matched": ["refs/heads/main"],
    "matches": [{"kind": "content", "refs": ["refs/heads/main"], "path": "src/api.py", "start_line": 42, "end_line": 42, "content": "# TODO"}],
    "owners": ["@acme/platform"],
    "synced_at": "2026-07-10T15:00:00+00:00"
  }],
  "failures": [],
  "summary": {"selected": 1, "prepared": 1, "scanned": 1, "matched": 1, "unscanned": 0, "refreshed": 1, "cached": 0, "oldest_fetched_at": "2026-07-10T15:00:00+00:00"}
}
```

Use `--columns ?` to list selectors. Content evidence may include clipped
source context with `--context N`; the option is content-primary-only.
CODEOWNERS is resolved per qualifying ref for primary-evidence paths only.

Default exit code is `0` for no matches, matches, and declared partial
reports. `--fail-on-match` promotes any match to exit `1`; `--require-complete`
promotes any unscanned repository to exit `1`.

Typed sweep records can feed another sweep because `--stdin` reads
`full_name` from pipe envelopes or bare owner/name lines:

```bash
untaped-github repos list 'svc-*' --org acme --format pipe \
  | untaped-github sweep content old_api --stdin --format pipe \
  | untaped-github sweep paths Jenkinsfile --stdin --cached
```

`untaped-workspace add --stdin` reads generic URL lines, not typed pipe
records. Use raw URL output when turning matching repos into a workspace:

```bash
untaped-github sweep content old_api --org acme \
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
worktrees before deleting a bare repo. `--prune` accepts `--org`, resolves
live inventory, and removes cached repos in that org that departed or are now
archived. `--prune` rejects `--team` because team membership is not recorded
in corpus metadata; use `--org` pruning or an explicit `--repo` clean instead.

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

Stable pipe kinds and identifiers:

| Producer | Kind | Identifier |
| -------- | ---- | ---------- |
| `whoami` | `github.user` | `login` |
| `repos list`, `search repos` | `github.repo` | `full_name` |
| `search code` | `github.code` | `name` |
| `search issues` | `github.issue` | `repo` |
| `search users` | `github.user` | `id` |
| `sweep content`, `sweep paths` | `github.sweep_result` | `full_name` |
| `cache status`, `cache clean` | `github.corpus_repo` | `repo` |
| `cache worktree` | `github.worktree` | `repo` |

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
