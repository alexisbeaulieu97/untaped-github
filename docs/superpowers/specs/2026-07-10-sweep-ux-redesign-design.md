# untaped-github sweep UX redesign — design spec

**Date:** 2026-07-10
**Status:** Approved for implementation
**Supersedes:**
[`2026-07-02-sweep-redesign-design.md`](2026-07-02-sweep-redesign-design.md)
**Scope:** `untaped-github` only. No SDK or `untaped-ansible` public-API
changes.

## Problem

The first question-first `sweep` implementation proved the local-corpus
architecture, but its command and output contracts still expose the engine
more than the user's question:

- one root command mixes four parallel predicate collections and an `--any`
  mode, so no single predicate clearly owns the evidence in the report;
- content regexes and path patterns inherit different, partly implicit Git
  behavior;
- output can switch between repo rows and match rows, which makes structured
  output a projection rather than a complete report;
- fetch depth and concurrency are ordinary flags even though they are tuning,
  not part of a sweep question; and
- short branch and tag names can collide and become ambiguous in evidence.

The redesign keeps the proven corpus engine and replaces the public sweep UX.
The core model is:

> scope × selected refs × one primary target × same-ref constraints → an
> evidence-first report

## Locked command surface

`sweep` becomes a sub-app with exactly two target commands:

```console
untaped-github sweep content REGEX [OPTIONS]
untaped-github sweep paths GLOB [OPTIONS]
```

The required positional value is the primary question and the only source of
reported match evidence:

- `sweep content REGEX` reports matching content locations;
- `sweep paths GLOB` reports matching repository paths.

Representative invocations:

```console
untaped-github sweep content 'requests\.get\(' --org acme
untaped-github sweep content old_api --org acme --without-content new_api
untaped-github sweep content TODO --team acme/platform \
  --include-path 'src/**' --exclude-path 'src/vendor/**' --context 2
untaped-github sweep paths 'Jenkinsfile' --org acme --with-path '.github/**'
untaped-github sweep paths '*.py' --org acme --without-content 'copyright'
untaped-github sweep content 'deprecated' --org acme --refs branches \
  --ref 'release/*' --fail-on-match --require-complete
```

The former root options `--grep`, `--not-grep`, `--has-file`, `--lacks-file`,
`--path`, `--any`, `--show`, `--owners`, `--depth`, `--parallel`, `--sync`,
`--no-sync`, `--archived`, and `--strict` are removed. There are no
compatibility aliases. Invocations using the old forms fail with a concise
migration-oriented error that points to `sweep content` or `sweep paths` and
the corresponding replacement option where one exists.

## Scope

Both target commands retain the same additive scope inputs:

- repeatable `--org ORG`;
- repeatable `--team ORG/SLUG`, with the existing bare-slug shorthand only
  when exactly one `--org` disambiguates it;
- repeatable `--repo OWNER/NAME`; and
- `--stdin`, accepting bare `owner/name` lines or pipe records with
  `full_name` as their identifier.

At least one scope input is required. Inputs are combined additively and
deduplicated by `full_name`. Archived repositories are excluded unless
`--include-archived` is passed.

Online runs resolve org and team membership live. `--cached` resolves scope
from corpus metadata without network access and rejects `--team`, because team
membership is not stored in the corpus. That rejection is preferable to
silently scanning an approximate scope.

## Primary target and constraints

Each invocation has exactly one primary matcher: the `REGEX` or `GLOB`
positional value. Constraints are repeatable and always conjunctive:

- `--with-content PATTERN`: content must occur;
- `--without-content PATTERN`: content must not occur;
- `--with-path PATTERN`: at least one path must match; and
- `--without-path PATTERN`: no path may match.

The primary matcher and every constraint must hold on the **same selected
ref**. A witness from one branch cannot satisfy a constraint for primary
evidence found on another branch. For each repository and selected ref:

1. evaluate the primary matcher;
2. evaluate every constraint on that ref;
3. retain the primary evidence only if every constraint passes; and
4. discard constraint witnesses from the report.

A repository is a result when at least one selected ref qualifies. There is
no `--any`, grouping, precedence, or expression grammar. Repetition means
AND. More complex set logic composes through pipe records and multiple sweep
invocations.

For a content matcher, a positive result means at least one non-binary content
hit. For a path matcher, a positive result means at least one tracked tree path
matches. The corresponding `without` form passes only when there are zero
hits.

## Content pattern contract

All content matchers — the content primary and every content constraint — use
one invocation-wide set of options:

- the default is a forced POSIX extended regular expression, independent of
  user Git configuration;
- `--fixed-strings` selects literal matching instead of ERE;
- `--ignore-case` makes content matching case-insensitive; and
- `--word-regexp` requires word-boundary matches.

Binary content is skipped. Every content pattern is validated before any
repository refresh begins. Actual newline characters are rejected. The
current engine is intentionally line-oriented: one hit has equal
`start_line` and `end_line`. The report schema uses a range now so a later
multiline engine can represent multi-line evidence without another output
contract change.

The modifiers apply to every content matcher in the invocation. On
`sweep paths`, they and the content path filters are valid only when at least
one `--with-content` or `--without-content` constraint exists; otherwise they
are usage errors because there is no content evaluation to modify.

### Content path filters

Repeatable `--include-path GLOB` and `--exclude-path GLOB` filter content
evaluation only. They apply to the content primary and all content constraints;
they never filter the path primary or path constraints.

The effective content candidate set is:

```text
(matches any include pattern, or all paths when no include was given)
AND does not match any exclude pattern
```

Exclusion always wins, including when a path also matches an include. For
example, `--include-path '**' --exclude-path '.github/**'` evaluates content
outside `.github/` only.

## Path pattern contract

All path matchers and content path filters use the same case-sensitive,
gitignore-style language implemented by `pathspec>=1.1.1,<2` and
`PathSpec.from_lines("gitignore", [pattern])`. `PathSpec.match_file` is the
sole authority for path meaning; public path patterns are not passed to Git as
Git pathspecs.

The contract includes rooted, nested, and basename patterns such as:

- `Jenkinsfile` matches that basename at any depth;
- `/Jenkinsfile` matches only the repository-root file;
- `.github/**` matches descendants of the repository-root `.github`
  directory (use `**/.github/**` to include nested directories); and
- `**/*.py` matches Python files recursively.

Negation belongs to the option name, not to the pattern language. An unescaped
leading `!` is rejected instead of changing a positive pattern into a negative
one. A leading literal exclamation mark may be escaped as `\!`. A comment-only
pattern is rejected; a leading literal number sign may be escaped as `\#`.
Invalid patterns and actual newline characters fail before refresh begins,
with a user-ready error naming the offending option and value.

## Revisions and canonical refs

Both commands retain:

- `--refs default|branches|tags|all`, defaulting to `default`; and
- repeatable `--ref GLOB`, unioned with the selected profile.

An explicit glob such as `release/*` selects matching branch and tag names.
Internally, through evaluation, grouping, and serialization, selected refs are
fully qualified: for example `refs/heads/release/1.0` and
`refs/tags/release/1.0`. A same-named branch and tag therefore remain distinct.
Reports never shorten canonical refs or merge them merely because their leaf
names collide.

Content evidence is grouped across refs only when blob identity, path,
`start_line`, `end_line`, and content are identical. Path evidence is grouped
across refs by identical path. The grouped `refs` array contains sorted,
deduplicated canonical refs. Distinct content at the same path and line remains
distinct evidence.

## Freshness and corpus policy

The managed corpus remains a bare, shallow, blobful content cache. Blobful is
load-bearing because `git grep <ref>` needs blobs locally; blobless fetches
would turn a sweep into repeated lazy network reads. Fetch profiles widen and
never narrow.

The freshness controls are:

- default: refresh uncached, stale, or under-profiled repositories;
- `--refresh`: force preparation of the whole selected scope; and
- `--cached`: make no network calls and use only corpus state that covers the
  requested refs.

`--refresh` and `--cached` are mutually exclusive. If a refresh fails but an
existing cache covers the requested selector, the repository is scanned from
cache. Otherwise it becomes a `prepare` failure. A scan error becomes a `scan`
failure. Failures do not erase successful results.

Operational tuning is configuration-only:

```yaml
github:
  sweep:
    fetch_depth: 1
    sync_concurrency: 12
    max_age_seconds: 3600
```

`fetch_depth` is non-negative (`0` requests full history),
`sync_concurrency` is positive and remains subject to the SDK parallel clamp,
and `max_age_seconds` is non-negative. These values are not command options:
changing corpus cost and refresh policy per invocation makes questions hard to
reproduce and clutters the normal UX with implementation tuning.

## Ownership

CODEOWNERS is read from each qualifying canonical ref. Owners are resolved only
for paths in retained **primary evidence**, using last-match-wins semantics.
Constraint witnesses never contribute owners. Missing CODEOWNERS produces an
empty owner set rather than a failure. Result-level `owners` is the stable,
deduplicated, lexically sorted union of owners resolved per qualifying ref and
primary-evidence path. Table output repeats that result-level union on every
primary-match row for the repository. This is intentionally not a ref/path
ownership-provenance mapping; callers that need that distinction must resolve
CODEOWNERS against the referenced evidence themselves.

There is no public owner toggle. Owner resolution is local and makes no GitHub
Teams API calls.

## Report model

One sweep always produces a complete report:

```text
SweepReport
├── query
├── results[]
├── failures[]
└── summary
```

`query` is the normalized effective query, including defaults:

```json
{
  "scope": {
    "orgs": ["acme"],
    "teams": [],
    "repos": [],
    "stdin": false,
    "include_archived": false
  },
  "question": {"kind": "content", "pattern": "TODO"},
  "constraints": [
    {"kind": "without_content", "pattern": "DONE"}
  ],
  "content_options": {
    "mode": "extended_regex",
    "ignore_case": false,
    "word_regexp": false
  },
  "path_filters": {"include": [], "exclude": []},
  "refs": {"profile": "default", "globs": []},
  "freshness": "auto",
  "context": 0
}
```

For `sweep paths`, `question.kind` is `"path"`. Constraint `kind` is exactly
`"with_content"`, `"without_content"`, `"with_path"`, or `"without_path"`.
`content_options.mode` is `"extended_regex"` or `"fixed_strings"`.
`freshness` is `"auto"`, `"refresh"`, or `"cached"`. Tuples serialize as
JSON/YAML arrays and timestamps serialize as ISO 8601 strings or null.

Each matching repository is one result. For a content question, for example:

```json
{
  "full_name": "acme/api",
  "clone_url": "https://github.com/acme/api.git",
  "refs_matched": ["refs/heads/main"],
  "matches": [
    {
      "kind": "content",
      "refs": ["refs/heads/main"],
      "path": "src/client.py",
      "start_line": 42,
      "end_line": 42,
      "content": "# TODO: replace client"
    }
  ],
  "owners": ["@acme/platform"],
  "synced_at": "2026-07-10T15:00:00+00:00"
}
```

A content match is:

```json
{
  "kind": "content",
  "refs": ["refs/heads/main"],
  "path": "src/client.py",
  "start_line": 42,
  "end_line": 42,
  "content": "# TODO: replace client",
  "context": {
    "start_line": 40,
    "end_line": 44,
    "content": "def request():\n    pass\n# TODO: replace client\nclient = old()\nreturn client"
  }
}
```

A path match is:

```json
{
  "kind": "path",
  "refs": ["refs/heads/main"],
  "path": "Jenkinsfile"
}
```

`--context N` is content-primary-only, defaults to `0`, and must be
non-negative. The optional `context` member is omitted when `N == 0`; when
present, it contains the clipped inclusive line range around the primary match
and its newline-joined source content. Context is presentation evidence, not
part of match identity. It does not turn nearby constraint witnesses into
reported evidence.

Each unscanned repository is represented separately:

```json
{"full_name": "acme/broken", "stage": "prepare", "reason": "fetch failed"}
```

`stage` is exactly `prepare` or `scan`. `summary` is:

```json
{
  "selected": 12,
  "prepared": 11,
  "scanned": 10,
  "matched": 3,
  "unscanned": 2,
  "refreshed": 4,
  "cached": 7,
  "oldest_fetched_at": "2026-07-10T14:00:00+00:00"
}
```

The invariants are:

- `prepared + prepare failures == selected`;
- `scanned + scan failures == prepared`;
- `unscanned == prepare failures + scan failures`;
- `matched == len(results)`;
- `refreshed + cached == prepared`; and
- `oldest_fetched_at` is the oldest timestamp among prepared repositories, or
  null when none were prepared.

### Deterministic ordering

Ordering is part of the serialized contract:

- requested scope lists (`orgs`, `teams`, and `repos`), constraints, path
  filters, and explicit ref globs preserve CLI order;
- `results` and `failures` sort lexically by `full_name`;
- canonical ref arrays and owner arrays sort lexically and are deduplicated;
- matches sort by (`kind`, `path`, `start_line`, `end_line`, `content`, sorted
  canonical `refs` tuple); path matches omit the inapplicable line and content
  keys but still use the canonical refs tuple as the final tie-breaker; and
- context preserves repository source-line order.

These rules make equivalent runs diffable without erasing the order in which
the user stated the question.

## Rendering contracts

Every format writes the summary and every unscanned failure to stderr. This is
intentional even when JSON/YAML also carry that information on stdout: status
remains visible beside redirected or piped result data.

- **JSON/YAML:** serialize the archival, self-contained top-level
  `{query, results, failures, summary}` object. Without `--columns`, every
  result is complete. With `--columns`, the wrapper remains the same,
  `query`/`failures`/`summary` remain complete, and every projected result
  retains mandatory `full_name` and `refs_matched` identity fields in addition
  to the selected optional fields.
- **Table:** one row per primary match. Content rows show repo, canonical refs,
  path, line range, content, optional context, and owners. Path rows show repo,
  canonical refs, path, and owners. Column selection always retains repo and
  canonical-ref identity. The same sorted result-level owner union is repeated
  on every match row. Failures and summary remain visible on stderr.
- **Raw:** without `--columns`, emit each matched `full_name` once. With
  columns, emit one row per matching repository; nested match selections are
  ordered arrays so a repository is never duplicated merely because it has
  several matches. Raw columns are intentionally a lossy, custom projection;
  unlike JSON/YAML, raw does not force identity or coverage fields into a
  requested projection.
- **Pipe:** emit one complete record per result with
  `kind="github.sweep_result"` and `id_field="full_name"`. Pipe records contain
  the full result object. `--columns` is ignored so downstream sweeps always
  receive a complete, stable record.

Raw and pipe stdout contain matching-result projections only: they do not
serialize failures or the summary and are not archival reports. An empty
raw/pipe stdout with exit `0` is intentional for both a clean no-match run and
a partial run with no matches; stderr distinguishes them through the mandatory
summary and failure lines. `--require-complete` additionally promotes any
unscanned repository to exit `1`.

`--columns ?` lists the exact valid selectors: `full_name`, `clone_url`,
`refs_matched`, `matches.kind`, `matches.refs`, `matches.path`,
`matches.start_line`, `matches.end_line`, `matches.content`,
`matches.context`, `owners`, and `synced_at`. Unknown selectors are usage
errors naming the selector.

The old `github.sweep_repo` and `github.sweep_match` output split is retired.
The one pipe kind is `github.sweep_result`.

## Exit policy

The default exit code is `0` for no matches, matches, and reports with declared
failures. Two explicit policies promote the result to exit `1`:

- `--fail-on-match` when any repository matched; and
- `--require-complete` when any repository is unscanned.

If both are supplied, either condition is sufficient. Usage/configuration and
unexpected operational errors retain the SDK's normal error handling. The old
`--strict` spelling is removed without an alias.

## Architecture mapping

- **domain/** owns immutable target, constraint, content-option, path-filter,
  ref-selector, match, result, failure, summary, and report value objects plus
  pure matching/grouping invariants.
- **application/** owns scope resolution, preparation, per-ref primary plus
  constraint evaluation, primary-evidence retention, context reads,
  CODEOWNERS enrichment, grouping, and summary accounting.
- **infrastructure/** owns canonical ref enumeration, forced ERE/fixed-string
  `git grep`, blob reads, tree reads, and the existing fetch-profile-aware
  corpus.
- **cli/** owns the target sub-app, migration errors, ordered help groups,
  config loading, report rendering, columns, and exit policy.

The root `untaped_github` public API used by `untaped-ansible` remains
unchanged.

## Documentation and verification obligations

The implementation change must update README, `docs/github.md`, `AGENTS.md`,
the packaged `SKILL.md`, settings documentation, pipe-kind tables, and tests
that pin help, entrypoints, layering, and public API. It is a breaking CLI and
output redesign and therefore releases as `0.15.0` after approval.

Verification must cover both target commands, same-ref constraints, content
modifiers, PathSpec semantics and validation, canonical branch/tag collisions,
include/exclude precedence, binary skipping, grouped evidence, context
boundaries, CODEOWNERS per ref, failures and summary invariants, every output
format, pipe chaining, migration errors, exit codes, and config-only tuning.

## Explicit non-goals

- GitHub Search as a sweep backend.
- A boolean expression grammar, grouping, or `--any`.
- Multiline matching in this wave; the range-shaped report is only
  multiline-ready.
- Constraint-witness output.
- GitHub Teams API owner enrichment.
- Inventory membership caching.
- Per-invocation depth, concurrency, or max-age tuning.
- Compatibility aliases for the 0.14 sweep surface.
- SDK changes, `untaped-ansible` corpus adoption, or release-workflow changes.
