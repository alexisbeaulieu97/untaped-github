# Architecture decisions

A short record of the decisions behind `untaped-github`'s design. These are
settled; this page is the reference, not a discussion. For the SDK-wide
decisions this tool inherits — the SDK-only direction, the
`~/.untaped/config.yml` format, and the `--format pipe` envelope — see the core
[`untaped` decisions](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/decisions.md).
The exact current sweep command and report contract is recorded in the
approved [sweep UX redesign spec](superpowers/specs/2026-07-10-sweep-ux-redesign-design.md);
the July 2 spec and July 6 implementation plan describe the superseded 0.14
surface and are retained only as historical implementation context.

## 1. `sweep` is question-first over a local corpus; the corpus is the engine, not GitHub Search

Team-wide code and file-presence checks are answered by a question-first
`sweep` workflow — scope × refs × question × constraints → an evidence-first
report — evaluated against a managed local Git corpus with `git`. `sweep` must
**not** call `/search/*`; online sweeps use REST inventory only to expand
`--org`/`--team`/`--repo` scopes, then fetch and inspect locally.

This replaced an earlier `scan` command tree. A backend-pluggable design
(`--backend corpus|api`) was considered and **rejected**. Primary-source
research showed GitHub's hosted code search cannot answer the same question
the corpus can: GraphQL has no code search at all, and the REST code-search
endpoint is the legacy engine — no regex, roughly nine requests per minute, a
silent 1000-result cap, and default-branch-only. A hosted backend would answer
a *weaker* question and produce silent false negatives, which is worse than a
slower but honest local answer.

Hosted `search` survives as a separate verb for ranked, indexed lookups
("what's out there?"), and `repos list` for complete org/team inventory. These
answer different questions than `sweep` ("which of my repositories match this
question?") and are deliberately kept distinct.

## 2. The primary target is explicit in a subcommand

The public entrypoints are `sweep content REGEX` and `sweep paths GLOB`. The
required positional value is the primary target and is the sole source of
reported match evidence.

This replaces the root command's parallel `--grep`, `--not-grep`,
`--has-file`, and `--lacks-file` collections. Those options forced the renderer
to treat every predicate as equally reportable even when the user wanted one
answer qualified by supporting conditions. An explicit target gives help,
validation, table columns, and evidence one unambiguous shape. There are no
compatibility aliases; old syntax fails with a migration-oriented error.

## 3. One primary question plus conjunctive same-ref constraints — no boolean mode

Repeatable `--with-content`, `--without-content`, `--with-path`, and
`--without-path` options are constraints. Every constraint is conjunctive and
must pass on the **same canonical ref** as the primary evidence. Constraint
witnesses qualify evidence but never become evidence themselves.

The earlier flat boolean model — positives AND by default, `--any` switching
positives to OR, negations remaining conjunctive — is retired. Although flat,
it still mixed selection and evidence and made the meaning of repo rows depend
on which predicates fired. Primary-plus-constraints expresses the common
question directly and avoids adding grouping, precedence, or an expression
grammar. Complex set logic composes through pipe records and multiple sweeps.

## 4. Content and paths have explicit, portable pattern languages

Content patterns are forced POSIX extended regular expressions by default,
independent of user Git configuration. `--fixed-strings` selects literal
matching; `--ignore-case` and `--word-regexp` are explicit invocation-wide
modifiers. Binary files are skipped and actual newlines in patterns are
rejected. The engine is line-oriented today, while its output range is
multiline-ready.

Path patterns are case-sensitive gitignore-style patterns interpreted only by
`pathspec>=1.1.1,<2`. They are never delegated to ambient Git pathspec
semantics. An unescaped leading `!` and comment-only patterns are rejected;
negation belongs to `without`/`--exclude-path`, not inside a pattern.
`--include-path` and `--exclude-path` filter content evaluation only, and
exclusion wins.

The rationale is reproducibility: a recorded sweep must mean the same thing
under hostile Git configuration and across the primary, constraints, and
filters. One path implementation also prevents `sweep paths` and content path
filters from drifting into subtly different glob languages.

## 5. A sweep has one complete report model with explicit output projections

JSON and YAML serialize one `{query, results, failures, summary}` report.
Each result contains the repository, canonical matched refs, primary matches,
owners, and freshness. Failures retain their `prepare` or `scan` stage, and the
summary retains selection and coverage accounting. A JSON/YAML column
projection always retains `full_name` and `refs_matched` for result identity,
while query, failures, and summary remain complete.

Table output has one row per primary match. Raw output keeps one repository row
so it can feed other tools without accidental duplicates. Pipe output emits
complete `github.sweep_result` records and ignores `--columns`; a projection
must never make a record unusable as the scope for another sweep. This replaces
the old `--show repos|matches` split and the separate `github.sweep_repo` and
`github.sweep_match` kinds. Table projection always keeps repository and ref
identity. Raw columns are intentionally lossy and custom.

Raw and pipe stdout remain matching-result projections, not archival reports.
Every run writes its summary and each unscanned failure to stderr, including an
otherwise empty, successful raw/pipe run. JSON/YAML are the archival formats.
This split keeps pipelines data-only without hiding coverage from the operator;
`--require-complete` is the explicit machine gate for any unscanned repository.

CODEOWNERS is resolved per qualifying ref and primary-evidence path. The result
stores a lexically sorted owner union, and table output repeats that union on
each match row. This intentionally favors a concise "who do I ping?" result
over a ref/path provenance mapping. Constraint witnesses do not affect owners.

Requested scope lists, constraints, filters, and ref globs preserve CLI order.
Results and failures sort by `full_name`; canonical refs and owners sort
lexically. Matches sort by kind, path, start line, end line, content, and the
sorted canonical refs tuple; path matches omit the inapplicable line and
content fields but still use refs as the final tie-breaker. Context remains in
source-line order. Stable ordering makes reports reproducible while preserving
the user's stated query.

## 6. Canonical refs survive selection, evaluation, grouping, and reporting

Refs remain fully qualified (`refs/heads/main`, `refs/tags/main`) from local
enumeration through serialization. A same-named branch and tag are distinct;
shortening them would corrupt provenance and can combine evidence from
different histories.

Content evidence groups refs only when blob identity, path, range, and content
are identical. Path evidence groups by path. Constraints are evaluated before
grouping and on the same ref as the primary evidence, so grouping cannot make a
cross-ref constraint appear satisfied.

## 7. Depth, concurrency, and max age are configuration-only tuning

Fetch depth, sync concurrency, and maximum cache age live under
`github.sweep` as `fetch_depth`, `sync_concurrency`, and `max_age_seconds`.
They are not ordinary sweep flags. Public freshness intent is limited to the
mutually exclusive `--refresh` and `--cached` controls; the default is automatic
refresh of uncached, stale, or under-profiled repositories.

These values change corpus cost and freshness policy, not the question being
asked. Keeping them in configuration makes invocations concise and repeatable
and avoids turning implementation tuning into a pseudo-query surface. The
defaults are depth 1, concurrency 12 before the SDK clamp, and max age 3600
seconds.

## 8. The corpus is a self-managing content cache, not a development workspace

The corpus at `github.corpus_path` (default `~/.untaped/github-corpus`) is a
managed cache of **bare, shallow, blobful** repositories, owned by the `sweep`
and `cache` command groups. It is explicitly not a human development workspace;
bulk dev checkouts remain `untaped-workspace`'s job.

- **Blobful is load-bearing.** Fetches stay blobful because `git grep <ref>`
  needs blobs present locally; `--filter=blob:none` is banned, since a blobless
  bare repo degrades into per-blob lazy fetches during grep.
- **Freshness is scope-bounded auto-sync.** Ordinary sweeps refresh only
  uncached, stale, or under-profiled repos; a cached default branch that differs
  from live inventory is under-profiled. `--refresh` forces preparation, and
  `--cached` reads only what corpus metadata already covers. Failed refreshes
  cannot fall back across a default-branch mismatch.
- **Fetch profiles only widen.** Corpus metadata records the fetched profile,
  ref globs, default branch, clone URL, and archived bit. A later narrow sweep
  can reuse a wider cache only while default-branch identity still matches.
- **Canonical default refs are mandatory.** Every selector includes and
  requires `refs/heads/<default_branch>` locally. Missing that ref is a declared
  scan failure even if another cached branch or tag survives.

The cache stores repository *content*, not scope *membership*: there is no
inventory-cache layer. Online runs resolve scopes live; `--cached` falls back
to corpus metadata only. This is why cached sweeps reject `--team` and
`cache clean --prune` accepts `--org` but rejects `--team` — team membership is
not locally decidable.

## 9. Fleet-standard exit codes use explicit match and completeness gates

`sweep` exits `0` for the ordinary cases: no matches, matches, and reports with
declared unscanned gaps. Promotion to exit `1` is opt-in — `--fail-on-match`
for any matching repository and `--require-complete` for any unscanned
repository.

An early sketch gave `sweep` grep-shaped exits and the first implementation
named its completeness gate `--strict`. Grep-shaped codes invert the natural
"fail if this pattern appears" CI idiom, and `strict` does not say what is
being required. Explicit match and completeness gates make both policies
auditable. A failed refresh can fall back to covering cache; otherwise its
declared failure is what `--require-complete` gates.

## 10. Git subprocess adapters must never inherit the CLI's stdio

The local Git adapter (`GitCorpusCache`) never lets a subprocess inherit the
CLI's stdio. Its `stdout` is a pipe when the caller captures output and
`DEVNULL` otherwise; its `stderr` is always a pipe.

A subprocess that inherits stdio writes straight into the CLI's own stdout, so
a first-time sweep's `git init`/fetch chatter leaked into `--format pipe` and
`--format raw` streams and corrupted machine-readable output. Capturing
`stderr` rather than discarding it also means a failed Git call surfaces the
real Git error instead of a bare nonzero exit.

The durable lesson: a test that asserts a subprocess "keeps existing
behavior" by locking stdio inheritance is a smell. Subprocess adapters isolate
their stdio by default.
