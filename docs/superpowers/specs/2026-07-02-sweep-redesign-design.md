# untaped-github sweep redesign — design spec

**Date:** 2026-07-02
**Status:** Approved design, awaiting implementation slot (see Sequencing)
**Scope:** untaped-github only. No SDK changes. No untaped-ansible changes.

## Problem

The CLI's inspection surface is organized by *mechanism*, not by the user's
question. `scan sync|grep|worktree|list|clean` makes the local git corpus a
first-class noun the user must operate (know it exists, sync it, then grep
it); `search code` is named after a GitHub API endpoint. The actual question —
"which repos in this scope match these patterns?" — has no verb. Four
concrete frictions, all confirmed against real usage:

1. **Two trees, manual backend choice.** The user must decide scan-vs-search
   before asking anything.
2. **Query expressiveness.** No way to express multiple patterns, path
   constraints, file-presence checks, or negation in one invocation.
3. **Corpus lifecycle is manual.** Sync-then-grep two-step; staleness is
   invisible; cache management is a user job.
4. **Output is not the deliverable.** The need is a repo-level report —
   shareable with teammates, enriched with owners, pipeable into
   untaped-workspace and other tools. `scan grep` emits raw grep lines.

## Research grounding (2026-07-02, primary sources)

These facts constrain the design and were verified against GitHub's own
documentation and schema:

- **GraphQL has no code search at all** (the `SearchType` enum has no CODE
  value). The REST `/search/code` endpoint runs GitHub's *legacy* engine:
  **no regex**, ~9 requests/minute, a **silent 1,000-result cap**,
  default-branch-only indexing, dormant repos dropped from the index,
  vendored/large files excluded, undocumented index lag.
- **Industry convergence:** no surveyed tool builds its scanner on the search
  API (turbolift, multi-gitter, CodeQL MRVA, Semgrep Managed Scans all
  treat it as a *shortlister* at most and clone to actually scan). The local
  mirror is the only complete option, and at this org scale (github.com,
  100–1000+ repos) it costs tens of GB — trivial.
- **Ownership:** there is no GitHub API for "who owns path X." Everyone
  parses CODEOWNERS themselves. Because the corpus is local clones,
  CODEOWNERS parsing costs **zero API requests**.
- **Storage:** GitHub's anti-shallow guidance targets long-lived clones with
  history needs. Blobless (`--filter=blob:none`) clones lazy-fetch missing
  blobs one round-trip at a time, which would make `git grep` over a bare
  corpus catastrophically slow. The existing bare + shallow + blobful corpus
  is the correct storage for a grep corpus and is **reaffirmed, not changed**.

Consequence: a backend-pluggable "sweep via corpus or API" abstraction was
considered and **rejected** — the API cannot express the query model below,
so the abstraction would produce silently-wrong results on one of its two
backends. The corpus is the sweep engine; hosted search survives separately
for what it is honestly good at (quick ranked lookups; issues/users/repos
search).

## Design

### The `sweep` verb

One question-first command. A sweep is **scope × refs × predicates → report**.

```
untaped-github sweep --org acme --grep 'requests\.get\(' --path 'src/**' --has-file Jenkinsfile
untaped-github sweep --team platform --grep 'log4j' --grep 'slf4j' --any
untaped-github sweep --org acme --grep old_api --not-grep new_api          # unmigrated repos
untaped-github sweep --org acme --ref 'release/*' --grep 'jenkins'
untaped-github repos list 'svc-*' --format pipe | untaped-github sweep --grep '...'
```

### Scope (which repos)

- `--org`, `--team` (repeatable), repo patterns — resolved through the
  existing public `ResolveRepositoryInventory`, unchanged.
- Piped repo records on stdin: any records carrying a `full_name` field
  (`org/repo`) are accepted as scope — the SDK's `read_identifiers` extracts
  by field, never by kind, so `github.repo` and `github.sweep_repo` records
  both work (Amendment 1). This makes sweep→sweep chains work.
- Archived repos are excluded by default; `--archived` opts in (matching
  `repos list` semantics).

### Refs (where in each repo)

Third axis of the query:

- `--refs default` (the default — today's behavior), `--refs branches`,
  `--refs tags`, `--refs all`.
- `--ref GLOB` (repeatable) for explicit ref patterns (`release/*`, `v2.*`).
- **Repo-level rule: a repo matches if any selected ref satisfies the
  predicate combination.** Repo rows report which refs matched; match-level
  output carries `refs[]` for every selected ref sharing the deduped blob
  (amended at plan review — see plan Amendments). Identical content reachable
  from multiple refs is deduplicated by blob OID in match display.
- Cost is opt-in and visible: disk and sync time scale with ref count.
  `default` stays the default; the cache never grows beyond what a sweep
  asked for; `cache status` reports per-profile disk.

### Predicates (what must hold)

Flat boolean model. Three mechanisms, no expression grammar:

1. **Content OR via regex alternation** inside a single pattern:
   `--grep 'log4j|slf4j'`.
2. **Cross-predicate AND by default**; one flag `--any` flips the repo-level
   combination of the *positive* predicates to OR. Negated predicates are
   always conjunctive filters, `--any` or not (Amendment 3).
3. **Negation on the predicate, not in a grammar**: `--not-grep`,
   `--lacks-file`.

Predicate inventory:

- `--grep PATTERN` (repeatable) — content regex, evaluated via `git grep`
  against the selected ref's tree.
- `--not-grep PATTERN` (repeatable) — requires zero matches.
- `--path GLOB` (repeatable) — constrains where `--grep`/`--not-grep` look
  (git pathspec). `--path` without any content predicate is an error that
  suggests `--has-file` (which is the presence check).
- `--has-file GLOB` / `--lacks-file GLOB` (repeatable) — file-presence
  checks against the ref's tree (`git ls-tree`), independent of content.

Evaluation is per repo per ref: each predicate independently produces a
boolean (plus hit counts for content predicates); repo-level set logic
combines them. **Explicit non-goals:** parentheses, nested groups, a
`--query file` structured form. The escape hatch for compound questions is
pipe composition (sweep→sweep, union/intersect of repo records). A
structured query file may be revisited if real usage shows recurring
multi-sweep pipelines — evidence-gated, per ecosystem discipline.

### Corpus & sync policy

The corpus becomes an invisible, self-managing cache:

- **Storage unchanged:** bare, shallow (depth 1), blobful. Refreshes are
  `fetch --depth 1` + ref reset (never pull). This reaffirms the existing
  documented decision; the rationale (blobless breaks bare `git grep`) is
  recorded above.
- **Fetch profiles:** per-repo cache metadata records which ref scope it
  holds (default / branches / tags / all / patterns), whether the repo was
  archived when synced, and when it was last fetched (amended at plan review —
  see plan Amendments). A sweep needing a wider profile widens the fetch for
  exactly the repos in its scope.
- **Scope-only auto-sync, freshness-bounded:** before scanning, any repo in
  scope staler than `max_age` (config `github.sweep.max_age`, default 1h) is
  refreshed. The org/team inventory is resolved live on every online sweep
  (one paginated request per ~100 repos — negligible; no inventory cache
  layer, Amendment 4), so new repos appear without a manual step. `--sync`
  forces a full refresh of the scope; `--no-sync` scans what is on disk
  (fully offline) and resolves scope from the corpus's own per-repo
  metadata instead of the API.
- **Freshness is visible, never silent:** the report footer states oldest
  fetch in scope and refreshed-vs-cached counts.
- **Failures don't kill the sweep:** a repo that cannot be fetched or
  scanned lands in an explicit "unscanned" bucket with the reason. Partial
  results always declare their gaps. `--strict` turns any gap into a
  nonzero exit.
- **First run is just a big sync:** empty corpus → clone everything in scope
  at bounded concurrency (default 12, configurable — under
  GitHub's secondary-rate-limit guidance) with SDK progress UX.
- **Lifecycle verbs shrink to `cache status | clean`.** Status: repo count,
  disk (per fetch profile), freshness spread. Clean: prune repos that left
  scope or were deleted/archived upstream. Worktree materialization survives
  as `cache worktree` (unchanged mechanics; demoted from the mental model).

### Output & pipe contract

- **Default: repo-level table.** One row per matching repo: repo, one column
  per predicate (hit counts, so `--any` sweeps show which pattern fired),
  refs matched (shown only when sweeping beyond default), owners. Footer:
  freshness summary + unscanned bucket.
- **`--show matches`:** line-level detail — repo, ref, path, line, excerpt.
- **Owners from CODEOWNERS in the corpus — zero API calls.** Per-matched-path
  resolution with proper last-match-wins semantics, aggregated to the repo
  row. Missing CODEOWNERS → empty column, never an error. `--no-owners`
  skips. **Non-goal:** Teams-API enrichment (burns the request budget;
  CODEOWNERS answers "who do I ping").
- **Pipe records** (ecosystem `--format pipe` conventions):
  - `github.sweep_repo` — id_field `full_name` (`org/repo`); fields include
    clone URL, per-predicate hit counts, refs matched, owners, synced-at.
    Designed so `sweep ... --format raw --columns clone_url |
    untaped-workspace add --stdin ...` clones exactly the flagged repos
    (amended at plan review — see plan Amendments). (Kind renamed by
    Amendment 1 — the SDK 3.0 kind grammar allows no third segment except
    `.summary`.)
  - `github.sweep_match` — full_name, refs[], path, line, text (with `--show
    matches`; amended at plan review — see plan Amendments).
- **Exit codes are fleet-standard** (Amendment 2): 0 = ran (matches or not,
  gaps declared in the footer), usage errors as usual; exit 1 comes only from
  the two promotion flags — `--strict` (any unscanned repo → failure) and
  `--fail-on-match` (any match → failure, the CI "this pattern must not
  exist" gate). Errors stay errors, never inverted away by shell `!`.

### Command-surface changes

- `sweep` — new, primary.
- `scan sync|grep|list|clean` — **removed** (dissolved into `sweep` +
  `cache`). `scan worktree` → `cache worktree`.
- `cache status|clean|worktree` — new group.
- `search repos|code|issues|users` — kept as-is; `search code` help text
  gains a pointer to `sweep` for exhaustive/regex/path queries and a note on
  the API's caps.
- `repos list`, `whoami` — unchanged.

### Ansible impact

None. untaped-ansible's contract surface (curated `untaped_github` public
API: `GithubClient` + the two GraphQL batch-ref-probe methods,
`ResolveRepositoryInventory`, scope/team helpers, `GithubGraphqlError`,
`GithubSettings`) is untouched. Sweep *reuses* `ResolveRepositoryInventory`
rather than forking it. The corpus remains outside the ansible contract
(unchanged status quo; ansible corpus adoption stays a separate design).

## Architecture mapping

Follows the existing clean-architecture layering:

- **domain/** — new sweep query model: predicate types, ref selectors,
  per-repo/per-ref evaluation results, repo-level combination logic
  (AND/`--any`/negation), CODEOWNERS resolution (pure: bytes in, owners
  out). All pure and unit-testable.
- **application/** — `Sweep` use case orchestrating: resolve scope (existing
  inventory port) → plan sync (fetch profiles + max-age) → sync stale
  (progress) → evaluate predicates per repo/ref (corpus port) → enrich
  owners → produce report model. Ports: `GitCorpus` protocol extends with
  fetch-profile-aware sync, multi-ref grep, tree file listing, and
  file-content read (for CODEOWNERS).
- **infrastructure/** — `git_corpus.py` gains: refspec construction per
  fetch profile, per-repo profile+freshness metadata, multi-ref `git grep`
  invocation with blob-OID dedup, `git ls-tree` file checks, `git cat-file`
  reads. No new transports.
- **cli/** — `sweep` command (thin; lazy imports per repo convention),
  `cache` group; `scan` tree deleted; `search code` help text updated.

## Error handling

- Per-repo fetch/scan failures → unscanned bucket (reason preserved), sweep
  continues. `--strict` → nonzero exit.
- Invalid regex / glob → immediate CLI error naming the offending flag value
  before any sync work starts.
- Offline + `--no-sync` with an empty corpus → clear error ("corpus has no
  repos in scope; run without --no-sync to populate").
- Rate-limit/auth errors during inventory resolution surface via existing
  SDK HTTP error handling; the corpus path uses git transport and is not
  subject to REST limits.

## Testing strategy

- Domain logic (predicate evaluation, combination semantics incl. `--any` +
  negation, ref selection, CODEOWNERS last-match-wins, blob dedup) — pure
  unit tests, no I/O.
- Corpus behavior (fetch profiles, widening, max-age staleness, prune,
  failure bucketing) — against local fixture git remotes on disk, as the
  existing corpus tests do. No live GitHub in CI.
- CLI surface — golden-ish table output tests per repo convention
  (color-strip caveats per AGENTS.md), pipe-record shape tests for the two
  new kinds, exit-code tests (0/1/strict).
- Contract guard: a test asserting the curated public `__init__` surface is
  unchanged (ansible contract).

## Versioning, docs, release

- CLI-breaking (removes `scan` verbs): MINOR bump pre-1.0 per ecosystem
  convention. Single release at the end of the implementation wave.
- Same-change updates required by workspace rules: AGENTS.md (scan → sweep +
  cache sections, corpus policy, new pipe kinds), packaged SKILL.md, README.
- No dependent migration needed (see Ansible impact) — verified, not assumed.

## Sequencing

Spec is approved and parked until an implementation slot opens. Per the
roadmap: after the remaining recipe waves and github's SDK 3.0 re-pin are
sequenced — the implementation plan is written only against landed code at
that point (module names above may shift with the 3.0 wave; the plan, not
this spec, absorbs that).

## Deferred / non-goals (explicit)

- Nested boolean query grammar and `--query file` form — evidence-gated.
- Teams-API owner enrichment — CODEOWNERS suffices; request budget.
- SSH remotes for the corpus — separate design (unchanged status quo).
- untaped-ansible corpus adoption — separate design (unchanged status quo).
- Hosted-search-as-shortlist optimization inside sweep — rejected for now;
  the full mirror is cheap at this org scale, and shortlist gaps are silent
  false negatives.

## Amendments (2026-07-06)

Joint spec re-review against landed code (github 0.13.0, untaped SDK 3.0 —
both shipped after this spec was locked). Body text above has been corrected
in place where it would otherwise mislead; each correction points here.

1. **Pipe kinds renamed: `github.sweep_repo` / `github.sweep_match`.** The
   originally specced `github.sweep.repo` / `github.sweep.match` are illegal
   under SDK 3.0's emit-time kind grammar (`<tool>.<noun>` in snake_case;
   the only permitted third segment is the literal `.summary`) — emitting
   them raises `ValueError` on the first row. The new names match the
   tool's existing `github.code_hit` / `github.corpus_repo` convention.
   Corollary: stdin scope acceptance is by the `full_name` field, not by
   kind — the SDK's `read_identifiers` never filters on kind.
2. **Exit codes: fleet-standard + `--fail-on-match`, replacing the
   grep-shaped contract.** "0 = matches, 1 = no matches" failed its own
   motivating use case: the CI "pattern must not exist" gate would be
   written `! sweep ...`, and shell negation converts *any* nonzero —
   including auth failures and usage errors — into a passing gate. Sweep
   now follows the fleet's `finish()` contract (0 clean, 1 per-repo
   failures, `--strict` promotes the unscanned bucket), and the CI gate is
   the explicit `--fail-on-match` flag: any match → exit 1, no matches →
   exit 0, errors remain distinct failures.
3. **`--any` combines positive predicates only.** Negated predicates
   (`--not-grep`, `--lacks-file`) are always conjunctive filters. A literal
   OR over negations ("contains A, or lacks B") matches nearly every repo —
   a footgun with no known use.
4. **No inventory cache layer.** The original "the org/team inventory obeys
   the same max-age" implied caching inventory results per scope — a whole
   new state layer. Instead: online sweeps resolve the inventory live every
   time (paginated listing, ~1 request per 100 repos), and `--no-sync`
   resolves scope from the corpus's per-repo metadata on disk, making
   offline sweeps self-contained. Repo-level `max_age` freshness is
   unaffected.
5. **Refs axis re-litigated and reaffirmed.** The multi-ref axis (`--refs`,
   `--ref` globs, fetch profiles, widening, blob-OID dedup) was challenged
   as the largest speculative corpus investment; Alexis ruled to keep it in
   v1 as specced.
