# Sweep Redesign Implementation Plan (untaped-github 0.14.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mechanism-first `scan` tree with the question-first `sweep` verb plus a `cache` lifecycle group, per the approved spec `docs/superpowers/specs/2026-07-02-sweep-redesign-design.md` (including its 2026-07-06 Amendments 1–5).

**Architecture:** Existing four-layer layout. New pure domain modules for the sweep query model and CODEOWNERS resolution; `GitCorpusCache` grows fetch-profile-aware sync and a multi-ref read surface; a new `Sweep` application use case orchestrates scope → sync → evaluate → owners → report; CLI gains `sweep` and `cache`, and `scan` is deleted.

**Tech Stack:** Python 3.14, untaped SDK (`untaped>=3.0.0,<4`), Cyclopts, pydantic, git subprocess (no new dependencies).

**Plan altitude:** This is a design brief. Interfaces, contracts, behaviors, and test intent below are **pinned**; function bodies, private helpers, and parsing mechanics are the implementer's. Where a step says "test intent", write real tests asserting exactly the named behaviors — test names are pinned so the review can map contract → lock.

## Global Constraints

- Spec of record: `docs/superpowers/specs/2026-07-02-sweep-redesign-design.md` @ PR #51 as merged (body text + Amendments 1–5). On any plan-vs-spec-vs-reality conflict: STOP and ask; do not improvise. Record every approved deviation in the PR body.
- Pipe kinds emitted by this wave: `github.sweep_repo`, `github.sweep_match`, `github.corpus_repo`, `github.worktree`. No dotted third segments — SDK 3.0 rejects them at emit time.
- The curated public surface `src/untaped_github/__init__.py` `__all__` is the ansible contract and must not change: `BatchRepoRefsFailure, BatchRepoRefsResult, GithubClient, GithubGraphqlError, GithubSettings, RepoRef, RepoRefs, RepositoryInventoryItem, RepositoryInventoryScope, ResolveRepositoryInventory, TeamScope, app, normalize_team_scopes`.
- `tests/unit/test_layering.py` and `tests/unit/test_tool_entrypoint.py` must stay green throughout (domain stays pure — no subprocess/network in `domain/`).
- Corpus storage policy unchanged: bare + shallow (depth 1 default, `depth=0` = full) + blobful; fetch + ref update, never pull; HTTPS auth header injection, path confinement, and secret scrubbing in `git_corpus.py` are reused, not reimplemented.
- No live GitHub in CI: corpus tests use on-disk `file://` fixture remotes (the existing `tests/unit/test_git_corpus.py` `_source_repo` pattern).
- Version lands at **0.14.0** (CLI-breaking pre-1.0 → MINOR). Release dispatch is Alexis's; no `.github/` workflow changes in this wave.
- Follow repo `AGENTS.md` for gate invocation and table-output color-strip caveats. Gate per task: `uv --cache-dir .uv-cache run pytest`, `uv --cache-dir .uv-cache run mypy src tests`, pre-commit. Commit at the end of every task.

## Pinned cross-task contracts

**Predicate labels** (column headers, `hits` keys, error messages): `grep:<pattern>`, `not-grep:<pattern>`, `has-file:<glob>`, `lacks-file:<glob>`.

**`github.sweep_repo` record** (one per *matching* repo): `full_name` (id_field), `clone_url`, `refs_matched: list[str]`, `hits: dict[str, int]` (predicate label → hit count; presence checks 1/0), `owners: list[str]`, `synced_at: str | None` (UTC isoformat of the corpus copy scanned). Table view: `full_name`, one column per predicate label, `refs_matched` (only when the ref selector goes beyond `default`), `owners`.

**`github.sweep_match` record** (with `--show matches`): `full_name`, `refs: list[str]` (all selected refs sharing the deduped blob), `path`, `line`, `text`.

**Exit codes:** `finish(promoted)` where `promoted = (--strict and unscanned bucket non-empty) or (--fail-on-match and any repo matched)`. Without promotion flags a sweep that ran exits 0, matches or not, gaps declared in the footer. Usage/config errors keep their normal paths.

**Sweep CLI flag set** (exact):
scope `--org`/`--team`/`--repo` (repeatable; team = `org/team-slug` via existing `normalize_team_scopes`), `--stdin`, `--archived`; predicates `--grep`/`--not-grep`/`--path`/`--has-file`/`--lacks-file` (repeatable), `--any`; content modifiers `--ignore-case/-i`, `--fixed-strings/-F`, `--word-regexp/-w` (apply to all content predicates); refs `--refs default|branches|tags|all` (default `default`), `--ref GLOB` (repeatable); sync `--sync`, `--no-sync` (mutually exclusive); output `--show repos|matches` (default `repos`), `--no-owners`, `--fmt`, `--columns`; exit `--strict`, `--fail-on-match`; perf `--depth` (default 1), `--parallel/-j` (default from settings, clamp cap 32 via existing `clamp_parallel`).

**Settings:** `GithubSettings` gains `sweep: SweepSettings` where `SweepSettings(BaseModel)` = `max_age_seconds: int = 3600`, `sync_concurrency: int = 12`. Config path: `github.sweep.max_age_seconds` etc. under the profile layout.

**Ref selection semantics:** selected refs = refs of the `--refs` profile ∪ local refs matching any `--ref` glob (globs match under both `refs/heads/` and `refs/tags/`). `--ref` without `--refs` keeps profile `default`, so the default branch is always in the selection. A repo matches if **any** selected ref satisfies the combination; `refs_matched` lists the ones that did.

**Combination semantics (Amendment 3):** negated predicates (`not-grep`, `lacks-file`) are always conjunctive. Positive predicates combine AND by default, OR under `--any`. Zero predicates → `ConfigError("sweep requires at least one predicate")`. `--path` with no content predicate → `ConfigError` suggesting `--has-file`.

**Corpus metadata v2** (`untaped-corpus.json`): existing keys `repo, ref, clone_url, fetched_at` plus `profile: str` and `ref_globs: list[str]`. Absent new keys read as `profile="default", ref_globs=[]` (existing corpora stay valid — no migration). Widening lattice: `default < branches`, `default < tags`, `branches|tags < all`; effective fetch scope = stored ∪ requested (profiles joined upward, globs unioned). Never narrow.

**Freshness/fallback ruling:** a repo whose refresh fails but whose cached copy already covers the requested ref scope is scanned from cache (counted "cached" in the footer), not bucketed; a repo with no usable copy (or an insufficient profile it failed to widen) goes to the unscanned bucket with the reason. Footer always reports scanned/refreshed/cached counts, oldest `fetched_at` in scope, and the unscanned bucket.

---

### Task 1: Domain sweep query model

**Files:**
- Create: `src/untaped_github/domain/sweep.py`
- Modify: `src/untaped_github/domain/__init__.py` (export new names)
- Test: `tests/unit/test_sweep_domain.py`

**Interfaces (produces):**
- `RefProfile = Literal["default", "branches", "tags", "all"]`
- `@dataclass(frozen=True) RefSelector: profile: RefProfile = "default"; globs: tuple[str, ...] = ()` with `def beyond_default(self) -> bool`
- `@dataclass(frozen=True) SweepQuery: greps: tuple[str, ...]; not_greps: tuple[str, ...]; paths: tuple[str, ...]; has_files: tuple[str, ...]; lacks_files: tuple[str, ...]; any_mode: bool; refs: RefSelector` with `def labels(self) -> tuple[str, ...]` (pinned label grammar, stable order: greps, not-greps, has-files, lacks-files) and `def validate(self) -> None` raising `ValueError` for the zero-predicate and path-without-content cases (CLI maps to `ConfigError`)
- `@dataclass(frozen=True) RefEvaluation: ref: str; hits: Mapping[str, int]` (label → count; presence checks 0/1)
- `def ref_matches(query: SweepQuery, evaluation: RefEvaluation) -> bool` — the Amendment 3 combination
- `@dataclass(frozen=True) RepoSweepOutcome: full_name: str; matched: bool; refs_matched: tuple[str, ...]; hits: Mapping[str, int] (aggregated across matched refs, per-label max); owners: tuple[str, ...]; synced_at: str | None`
- `def profile_join(stored: RefProfile, requested: RefProfile) -> RefProfile` — the widening lattice

**Steps:**
- [ ] Write failing tests pinning: label grammar and order (`test_labels_are_flag_value_pairs_in_stable_order`); AND default across mixed positives (`test_all_positive_predicates_must_hit`); `--any` ORs positives only while negations stay conjunctive (`test_any_ors_positives_and_negations_still_veto`); negation-only query matches when negations hold (`test_negation_only_query_matches_clean_repo`); zero predicates and path-without-content raise (`test_zero_predicates_is_invalid`, `test_path_without_content_predicate_is_invalid`); widening lattice table incl. idempotence and `all` absorbing (`test_profile_join_lattice`).
- [ ] Implement `domain/sweep.py`; run the tests to green.
- [ ] Gate + commit (`feat: sweep domain query model`).

### Task 2: Domain CODEOWNERS resolver

**Files:**
- Create: `src/untaped_github/domain/codeowners.py`
- Modify: `src/untaped_github/domain/__init__.py`
- Test: `tests/unit/test_codeowners.py`

**Interfaces (produces):**
- `CODEOWNERS_LOCATIONS: tuple[str, ...] = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")` — GitHub's documented search order; first found wins
- `def parse_codeowners(text: str) -> CodeownersRules` (comments/blank lines skipped; malformed lines skipped, never raised)
- `CodeownersRules.owners_for(path: str) -> tuple[str, ...]` — last matching rule wins, exactly GitHub's semantics for the pattern forms we support: `*`, `/rooted/`, `dir/`, `*.ext`, `**` globs
- `CodeownersRules.default_owners() -> tuple[str, ...]` — owners of the bare `*` rule if present, else `()`

**Steps:**
- [ ] Write failing tests pinning: last-match-wins with an earlier broader rule (`test_last_matching_rule_wins`); rooted vs unrooted patterns (`test_unrooted_pattern_matches_any_depth`, `test_rooted_pattern_matches_from_root_only`); directory-suffix rules cover contained files (`test_directory_rule_owns_contained_files`); rule with no owners clears ownership (`test_owner_less_rule_unsets_owners`); malformed lines skipped (`test_malformed_lines_are_ignored`); `default_owners` from `*` (`test_default_owners_come_from_star_rule`).
- [ ] Implement; green; gate + commit (`feat: pure CODEOWNERS resolution`).

### Task 3: Corpus fetch profiles and profile-aware sync

**Files:**
- Modify: `src/untaped_github/infrastructure/git_corpus.py`, `src/untaped_github/domain/models.py` (`CorpusRepoResult` gains `profile: str = "default"`)
- Test: `tests/unit/test_git_corpus.py` (extend)

**Interfaces (produces, on `GitCorpusCache`):**
- `def sync_repo(self, repo: CorpusRepoTarget, *, root: Path, selector: RefSelector, depth: int, auth_header: str | None) -> CorpusRepoResult` — generalizes `sync_default_branch` (which it replaces): builds refspecs for the *effective* scope (stored metadata ∪ requested selector, per `profile_join`/glob union), fetches shallow, updates local refs, writes metadata v2. `default` profile refspec = the target's default branch (today's behavior); `branches` = `+refs/heads/*`; `tags` = `+refs/tags/*`; `all` = both; each glob adds matching head+tag refspecs.
- `def repo_freshness(self, repo: CorpusRepoTarget, *, root: Path) -> CorpusFreshness | None` where `@dataclass(frozen=True) CorpusFreshness: fetched_at: datetime; profile: RefProfile; ref_globs: tuple[str, ...]` (None = not cached). Replaces `has_default_branch` for staleness decisions.
- `def covers(freshness: CorpusFreshness, selector: RefSelector) -> bool` (module-level, pure): stored scope already includes the requested one.
- Metadata v1 files (no `profile` key) load as `profile="default", ref_globs=()`.

**Steps:**
- [ ] Write failing tests on `file://` fixtures: v1 metadata reads as default profile (`test_v1_metadata_reads_as_default_profile`); widening default→branches fetches new branch refs and records the joined profile (`test_sync_widens_profile_and_keeps_union`); re-sync never narrows (`test_sync_with_narrower_request_keeps_stored_scope`); glob fetch brings matching branches and tags only (`test_ref_glob_fetches_matching_refs_only`); `covers` truth table (`test_covers_selector_containment`).
- [ ] Implement; keep existing auth/confinement/atomic-metadata mechanics untouched; green; gate + commit (`feat: fetch-profile-aware corpus sync`).

### Task 4: Corpus read surface — multi-ref grep, tree checks, file reads

**Files:**
- Modify: `src/untaped_github/infrastructure/git_corpus.py`, `src/untaped_github/domain/models.py`
- Test: `tests/unit/test_git_corpus.py` (extend)

**Interfaces (produces, on `GitCorpusCache`):**
- `def local_refs(self, repo: CorpusRepoTarget, *, root: Path, selector: RefSelector) -> tuple[str, ...]` — cached refs matching the selector, short names, default branch first, then sorted.
- `def grep_ref(self, repo, *, root, ref: str, pattern: str, paths: tuple[str, ...], ignore_case: bool, fixed_strings: bool, word_regexp: bool) -> tuple[GrepHit, ...]` where `@dataclass(frozen=True) GrepHit: path: str; line: int; text: str; blob_oid: str`. Reuses today's `git grep` invocation shape (returncode 1 = no match = `()`, >1 = `GitCorpusError`); blob OID obtained per matched path for dedup.
- `def tree_paths(self, repo, *, root, ref: str) -> tuple[str, ...]` — `ls-tree -r --name-only`; presence-glob matching happens in the application layer with `fnmatch`-style semantics.
- `def read_blob(self, repo, *, root, ref: str, path: str) -> str | None` — CODEOWNERS reads; None when absent; non-UTF-8 decodes as errors="replace" (owners are best-effort, never fatal).
- `def validate_pattern(self, *, root: Path, pattern: str, fixed_strings: bool) -> str | None` — exercises `git grep` against an empty scratch repo under `root`; returns the git error message for an invalid pattern, None when fine. (Mechanism is implementer's choice as long as invalid patterns are caught before any sync work, offline, with the message preserved.)
- Delete `grep_default_branch` (superseded); `CodeHitResult` is retired with it in Task 7 when its last consumer (scan) goes.

**Steps:**
- [ ] Write failing tests: multi-ref grep returns per-ref hits with blob OIDs and identical blobs share the OID across refs (`test_grep_hits_carry_blob_oid_shared_across_refs`); no-match ref returns empty, invalid pattern raises with git's message (`test_grep_no_match_vs_invalid_pattern`); `local_refs` ordering and glob filtering (`test_local_refs_default_first_then_sorted`); `tree_paths` lists nested files (`test_tree_paths_recursive`); `read_blob` present/absent (`test_read_blob_returns_none_for_missing_path`); `validate_pattern` catches a bad regex offline (`test_validate_pattern_flags_invalid_regex`).
- [ ] Implement; green; gate + commit (`feat: multi-ref corpus read surface`).

### Task 5: Settings, port extension, and the Sweep use case

**Files:**
- Modify: `src/untaped_github/settings.py`, `src/untaped_github/application/ports.py` (`GitCorpus` protocol mirrors Tasks 3–4 surface, drops `sync_default_branch`/`has_default_branch`/`grep_default_branch`), `src/untaped_github/application/__init__.py`
- Create: `src/untaped_github/application/sweep.py`
- Test: `tests/unit/test_sweep_use_case.py`, `tests/unit/test_settings.py` (extend if present, else assert via existing settings tests file)

**Interfaces (produces):**
- `SweepSettings` / `GithubSettings.sweep` per the pinned contract.
- `@dataclass(frozen=True) SweepOptions: scope: RepositoryInventoryScope; stdin_repos: tuple[str, ...]; include_archived: bool; query: SweepQuery; sync: Literal["auto", "force", "off"]; max_age_seconds: int; depth: int; parallel: int; owners: bool`
- `@dataclass(frozen=True) SweepReport: rows: tuple[RepoSweepOutcome, ...] (matching repos only, sorted by full_name); matches: tuple[SweepMatch, ...]; unscanned: tuple[CorpusFailure, ...]; scanned: int; refreshed: int; cached: int; oldest_fetched_at: datetime | None` with `@dataclass(frozen=True) SweepMatch: full_name: str; refs: tuple[str, ...]; path: str; line: int; text: str`
- `class Sweep:` constructed with the inventory use case, the corpus port, corpus root, and auth header supplier; `__call__(self, options: SweepOptions) -> SweepReport`.

**Behavior contracts:**
- Scope: `sync != "off"` → resolve via `ResolveRepositoryInventory` (stdin full names enter `scope.repos`), drop archived unless `include_archived`. `sync == "off"` → scope from corpus metadata (`--org` prefix match on `full_name`, explicit repos by name; teams raise `ConfigError("--team requires the API and cannot resolve offline")`); empty offline scope raises `ConfigError("corpus has no repos in scope; run without --no-sync to populate")`.
- Sync plan: `force` refreshes every repo in scope; `auto` refreshes repos that are uncached, under-profiled (`not covers(...)`), or staler than `max_age_seconds`; concurrent via the existing `bounded_map` at `parallel`, with SDK progress.
- Fallback ruling (pinned above): failed refresh + covering cache → scan cached, count as `cached`; failed refresh + no covering cache → `unscanned`.
- Evaluate: per repo, per selected local ref → `RefEvaluation` from grep counts (with `--path` pathspecs) and tree presence checks; `ref_matches` decides; matches deduped by `blob_oid` across refs into `SweepMatch.refs`.
- Owners: matched repos only, `options.owners` gated; CODEOWNERS read from the default branch via `CODEOWNERS_LOCATIONS` order; owners aggregated over the repo's matched paths (content-hit paths ∪ presence-glob-matched paths), falling back to `default_owners()` when the match set is pathless (pure `lacks-file`/`not-grep` sweeps). Missing/unparseable CODEOWNERS → `()`, never an error.
- Per-repo scan exceptions (`GitCorpusError`) → `unscanned`, sweep continues.

**Steps:**
- [ ] Write failing use-case tests with a fake corpus + fake inventory service pinning each behavior contract: offline scope filtering and both offline errors (`test_offline_scope_from_corpus_metadata`, `test_offline_team_scope_rejected`, `test_offline_empty_scope_rejected`); auto-sync refresh set (stale + under-profiled + uncached, fresh skipped) (`test_auto_sync_refreshes_only_stale_or_underprofiled`); fallback ruling both arms (`test_failed_refresh_with_covering_cache_scans_cached`, `test_failed_refresh_without_cache_is_unscanned`); any-ref-matches + refs_matched (`test_repo_matches_when_any_ref_matches`); blob dedup aggregating refs (`test_identical_blob_across_refs_yields_one_match_row`); owners aggregation + pathless fallback + missing file (`test_owners_from_matched_paths`, `test_pathless_match_uses_default_owners`, `test_missing_codeowners_is_empty`); archived filtering (`test_archived_repos_excluded_by_default`); settings defaults (`test_sweep_settings_defaults`).
- [ ] Implement; green; gate + commit (`feat: sweep application use case`).

### Task 6: The sweep CLI command

**Files:**
- Create: `src/untaped_github/cli/sweep_commands.py`
- Modify: `src/untaped_github/cli/commands.py` (mount `sweep`)
- Test: `tests/unit/test_sweep_cli.py`

**Behavior contracts:**
- Exact flag set as pinned. Lazy imports per repo convention; scope requirement mirrors scan's: no `--org/--team/--repo/--stdin` → `ConfigError`.
- Upfront validation order, all before any sync: query validation (domain `validate()` mapped to `ConfigError`), then every content pattern through `validate_pattern` — error message names the flag and value (e.g. `--grep 'foo['`: git's message).
- Rendering: `render_rows(..., kind="github.sweep_repo")` for `--show repos` (default), `kind="github.sweep_match"` for `--show matches`; record shapes exactly as pinned. Footer via `ui_context` messages: `Sweep: N matched of M scanned (R refreshed, C cached), oldest fetch <ts>` plus, when non-empty, a warning listing the unscanned bucket (repo + reason).
- `--stdin` uses `read_identifiers(positional=[], stdin=True, id_field="full_name")`.
- Exit: the pinned `finish(promoted)` contract.
- `--parallel` default from `settings.sweep.sync_concurrency`, clamped (cap 32); `--depth` default 1.

**Steps:**
- [ ] Write failing CLI tests against `file://` fixture repos (the `test_scan_cli.py` pattern): repo-table happy path with per-predicate columns (`test_sweep_table_has_predicate_columns`); pipe shape for both kinds incl. envelope + id_field (`test_sweep_repo_pipe_record_shape`, `test_sweep_match_pipe_record_shape`); `refs_matched` column appears only beyond default (`test_refs_column_only_when_selector_beyond_default`); invalid regex fails fast naming the flag, before sync (`test_invalid_pattern_errors_before_sync`); `--path` without content predicate suggests `--has-file` (`test_path_without_content_suggests_has_file`); exit-code matrix: clean no-match = 0, `--fail-on-match` with a match = 1, unscanned default = 0, `--strict` + unscanned = 1 (`test_exit_code_matrix`); stdin scope (`test_stdin_full_names_enter_scope`); `--no-owners` drops the owners column (`test_no_owners_skips_enrichment`).
- [ ] Implement; green; gate + commit (`feat: sweep CLI verb`).

### Task 7: The cache group; scan tree removed

**Files:**
- Create: `src/untaped_github/cli/cache_commands.py`
- Delete: `src/untaped_github/cli/scan_commands.py`, `tests/unit/test_scan_cli.py`
- Modify: `src/untaped_github/application/scan.py` → rename to `src/untaped_github/application/cache.py`; `src/untaped_github/cli/commands.py` (mount `cache`, unmount `scan`); `tests/unit/test_scan_use_cases.py` → `tests/unit/test_cache_use_cases.py`
- Test: `tests/unit/test_cache_cli.py`

**Behavior contracts:**
- `SyncCorpus` and `GrepCorpus` are deleted (dissolved into `Sweep`). `ListCorpus` becomes `StatusCorpus`: per-repo rows gain `profile` and `disk_bytes` (recursive size of the bare dir); kind stays `github.corpus_repo`; summary message reports repo count, total disk, and freshness spread (oldest/newest `fetched_at`).
- `CleanCorpus` keeps `--repo`/`--all` semantics (batch_apply destructive, `--yes`, kind `github.corpus_repo`) and gains `--prune` with scope flags (`--org`/`--team`): resolves live inventory and removes cached repos in scope no longer present or now archived. Exactly one of `--repo`/`--all`/`--prune` required.
- `cache worktree` = today's `scan worktree` verbatim (positional repo, `--ref`, kind `github.worktree`).
- Existing corpus-behavior test coverage from the deleted scan tests is preserved by porting the cases to the cache/sweep suites — behavior locks are moved, not dropped. Note survivals/retirements in the PR body.

**Steps:**
- [ ] Write failing tests: status rows carry profile + disk and the summary line (`test_cache_status_reports_profile_disk_freshness`); prune removes departed/archived repos only, with confirm flow (`test_cache_prune_removes_departed_repos`); clean flag exclusivity (`test_cache_clean_requires_exactly_one_mode`); worktree parity (`test_cache_worktree_materializes_cached_ref`).
- [ ] Implement the group, delete the scan tree, port surviving cases; green; gate + commit (`feat: cache lifecycle group replaces scan tree`).

### Task 8: search-code pointer and public-surface guard

**Files:**
- Modify: `src/untaped_github/cli/search_commands.py` (help text only)
- Create: `tests/unit/test_public_surface.py`

**Behavior contracts:**
- `search code` help gains one sentence pointing at `sweep` for exhaustive/regex/path/negation queries and naming the API's caps (no regex, 1000-result cap, default branch only). No behavior change.
- `test_public_surface.py` asserts `untaped_github.__all__` equals the pinned 13-name tuple exactly (the ansible contract lock).

**Steps:**
- [ ] Write the guard test (fails only if the surface drifted — expected to pass immediately); adjust help text; assert help output mentions sweep (`test_search_code_help_points_to_sweep`).
- [ ] Gate + commit (`docs: search code points to sweep; guard public surface`).

### Task 9: Docs sweep

**Files:**
- Modify: `README.md`, `AGENTS.md`, the packaged `SKILL.md`

**Behavior contracts:**
- AGENTS.md: scan sections replaced by sweep + cache (command surface, corpus policy incl. fetch profiles and the freshness/fallback ruling, new pipe kinds, exit-code contract).
- SKILL.md (source artifact rule): sweep-first workflow — question-first examples from the spec, `--fail-on-match` CI gate, sweep→sweep and sweep→workspace pipe recipes, `cache status|clean|worktree`, freshness footer semantics.
- README: command table + examples updated; SDK-setup guidance keeps linking to `untaped/docs/plugins.md`, not duplicating it.

**Steps:**
- [ ] Update all three in one commit; grep the repo for lingering `scan sync`/`scan grep`/`github.sweep.` references (`docs: sweep-first documentation`).

### Task 10: Version 0.14.0 and the full gate

**Files:**
- Modify: `pyproject.toml` (0.14.0), `uv.lock`, `CHANGELOG.md` if the repo keeps one

**Steps:**
- [ ] Bump version, `uv lock`, run the repo's release checks (version-consistency script if present).
- [ ] Full gate: pre-commit run --all-files; `uv --cache-dir .uv-cache run mypy src tests`; full pytest with coverage; `uv build`.
- [ ] Smoke: `uv --cache-dir .uv-cache run untaped-github sweep --help`, `... cache status --fmt table` against a scratch corpus, and one end-to-end sweep over a local `file://` fixture repo (match + `--fail-on-match` exit 1 observed).
- [ ] Commit (`chore: release 0.14.0`); open the PR with the deviations/errata section.

## Self-review notes (writing-plans checklist)

- Spec coverage: every spec section maps to a task — verb/predicates/refs (1, 3–6), corpus policy (3–5), output/pipe/exit (6), command surface (6–8), CODEOWNERS (2, 5), ansible guard (8), docs/versioning (9–10). Amendments 1–5 are each pinned in "Pinned cross-task contracts".
- Deliberate interpretations recorded here rather than silently: the freshness/fallback ruling; owners read from the default branch only; `--ref` globs union with the default branch; `validate_pattern` via scratch-repo git-grep. If reality contradicts any of these, STOP and escalate rather than improvise.
- Type consistency: `RefSelector`/`SweepQuery`/`RefEvaluation`/`RepoSweepOutcome` names used identically in Tasks 1, 3–6; corpus surface names in Tasks 3–5 match the port update in Task 5.
