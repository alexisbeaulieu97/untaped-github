---
name: untaped-github
description: Use the untaped GitHub plugin.
---

# Untaped GitHub

Use this skill when the user wants an agent to operate `untaped github` for authenticated GitHub user and search workflows.

## Setup

- The plugin command group is `untaped github`.
- Settings live under `profiles.<name>.github`: `base_url` and `token`.
- `github.base_url` defaults to `https://api.github.com`; GitHub Enterprise Server usually uses `https://HOST/api/v3`.
- Use `untaped config set github.token --prompt` or `--stdin` for tokens.

## Command Patterns

- `untaped github whoami` verifies the authenticated token and returns the current user.
- `untaped github search repos` searches repositories.
- `untaped github search code` searches code and does not support sort.
- `untaped github search issues` searches issues and pull requests.
- `untaped github search users` searches users and organizations.
- Search commands support scoped selectors such as `--user`, repeatable `--org`, repeatable `--repo`, and `--team` where applicable.

## Agent Guidance

- Prefer `--format json` for structured search results.
- Use `--limit` intentionally; GitHub search has stricter rate limits than normal REST reads.
- When no repo/org/user/team scope is passed to repo/code/issue search, the plugin defaults to the authenticated user.
- Repeated repo scopes are ORed together; do not rewrite them as separate AND qualifiers.
