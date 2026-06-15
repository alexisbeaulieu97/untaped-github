---
name: untaped-github
description: Use the untaped-github CLI.
---

# untaped-github

Use this skill when the user wants an agent to operate the `untaped-github` CLI for authenticated GitHub user and search workflows.

## Setup

- `untaped-github` is a standalone CLI built on the untaped SDK. Install it with `uv tool install untaped-github`.
- Settings live under `profiles.<name>.github`: `base_url` and `token`.
- `base_url` defaults to `https://api.github.com`; GitHub Enterprise Server usually uses `https://HOST/api/v3`.
- Set the token with `untaped-github config set token --prompt` or `--stdin` (a bare key addresses this tool's own section).
- Set the base URL with `untaped-github config set base_url https://HOST/api/v3`.

## Command Patterns

- `untaped-github whoami` verifies the authenticated token and returns the current user.
- `untaped-github search repos` searches repositories.
- `untaped-github search code` searches code and does not support sort.
- `untaped-github search issues` searches issues and pull requests.
- `untaped-github search users` searches users and organizations.
- Search commands support scoped selectors such as `--user`, repeatable `--org`, repeatable `--repo`, and repeatable `--team ORG/SLUG` where applicable.
- Always include the owning organization in the `--team` value.

## Agent Guidance

- Prefer `--format json` for structured search results.
- Use `--format pipe` to chain a search into another untaped tool: each
  record is tagged (`github.repo`/`github.code`/...), and `--repo-stdin` reads a
  `--format pipe` stream back (mapping `full_name`) as well as bare `owner/name`
  lines — e.g. `untaped-github search repos --org acme --format pipe |
  untaped-github search code "BaseModel" --repo-stdin`.
- `--profile <name>` works in any token position (e.g. `untaped-github --profile work whoami`).
- Use `--limit` intentionally; GitHub search has stricter rate limits than normal REST reads.
- When no repo/org/user/team scope is passed to repo/code/issue search, the CLI defaults to the authenticated user.
- Repeated repo scopes are ORed together; do not rewrite them as separate AND qualifiers.
