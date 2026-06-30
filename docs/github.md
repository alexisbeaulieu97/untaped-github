# GitHub

`untaped-github` is a standalone CLI, built on the
[`untaped`](https://github.com/alexisbeaulieu97/untaped) SDK, that inspects
the authenticated user, lists complete org/team repository inventory, and
searches GitHub for repositories, code, issues/PRs, and users/orgs. All
commands authenticate with the token from the tool's `token` setting.
Scoped search commands default to the authenticated user, so bare scoped
searches answer "what's mine?".

## Setup

```bash
uv tool install git+https://github.com/alexisbeaulieu97/untaped-github.git
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
automatically split across multiple `/search/repositories` requests when one
generated OR query would exceed GitHub's query-length validation. The final
rows are deduped by `full_name` and `--limit` is applied after all batches.
Batching prevents oversized team searches from failing with 422, but sorted
or best-match results are ordered per batch rather than as one global GitHub
ranking.

Repository-specific: `--name`, `--language`, `--archived/--no-archived`,
`--fork/--no-fork`, `--visibility public|private`, `--sort stars|forks|updated`.

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
