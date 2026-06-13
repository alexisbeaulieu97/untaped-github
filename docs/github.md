# GitHub

The GitHub plugin inspects the authenticated user and searches GitHub for
repositories, code, issues/PRs, and users/orgs. All commands authenticate
with the token from `github.token`. Scoped search commands default to the
authenticated user, so bare scoped searches answer "what's mine?".

## Setup

```bash
untaped config set github.token ghp_xxx        # personal access token
untaped github whoami                           # confirm it works
```

Profile selection is the root `--profile <name>` option contributed by the
[`untaped-profile`](https://github.com/alexisbeaulieu97/untaped-profile)
plugin (install it to use profiles); place it before the command group:
`untaped --profile work github whoami`.

The token is stored as a secret: `untaped config list` shows `***`, not
the value. See the core
[`configuration.md`](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/configuration.md)
for the full config model.

You can also override the API base URL. For GitHub Enterprise Server,
use the API path:

```bash
untaped config set github.base_url https://github.example.com/api/v3
```

## Commands

### `whoami`

```bash
untaped github whoami
untaped --profile work github whoami
untaped github whoami --format json
untaped github whoami --format raw --columns login
```

Calls `GET /user` and prints the authenticated user's profile. It is
pipe-friendly for shell prompts and scripts:

```bash
echo "[gh:$(untaped github whoami --format raw --columns login)]"
```

### `search`

`untaped github search` exposes one subcommand per GitHub search endpoint.
Every scoped subcommand defaults to `user:@me` when you pass no `--user`,
`--org`, `--repo`, or `--team`.

```bash
untaped github search repos --language python
untaped --profile work github search repos --language python
untaped github search repos --name client --language Go
untaped github search repos --org acme --visibility private
untaped github search repos --team acme/backend
untaped github search code "TODO" --language python
untaped github search issues --state open --label bug --kind pr
untaped github search users --kind org --location montreal
```

Common flags for `repos`, `code`, and `issues`:

| Flag          | Effect                                                               |
| ------------- | -------------------------------------------------------------------- |
| `--user`      | `user:<login>` qualifier; pass `@me` to be explicit.                 |
| `--org`       | `org:<name>` qualifier; repeatable.                                  |
| `--repo`      | `repo:owner/name`; repeated values render as an OR scope group.       |
| `--repo-stdin`| Read `owner/name` repo scopes from stdin and append to `--repo`.      |
| `--team ORG/SLUG` | Resolves the team's repos into an OR repo scope; repeatable.    |
| `--limit N`   | Stop after N rows. Default `30`; GitHub search caps at 1000 rows.    |
| `--format`    | `table` (default), `json`, `yaml`, `raw`.                            |
| `--columns`   | Repeatable; dotted paths supported.                                  |

`--team` must be self-contained as `ORG/SLUG`; `--org` remains a search
qualifier and does not provide the organization for a bare team slug.

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
untaped github search code "func init" --language go
untaped github search issues "memory leak" --state open
```

## Pipe-Friendly Examples

```bash
untaped github search repos --language python --format raw

untaped github search repos --org acme --format raw \
  | untaped github search code "TODO" --repo-stdin --format raw --columns repo --columns path

untaped github search repos --org acme --format raw \
  | untaped github search issues --state open --repo-stdin \
      --format raw --columns repo --columns number --columns title
```

## See Also

- [`untaped` configuration docs](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/configuration.md)
  for profiles, secrets, and TLS.
- [AGENTS.md](../AGENTS.md) for development rules.
