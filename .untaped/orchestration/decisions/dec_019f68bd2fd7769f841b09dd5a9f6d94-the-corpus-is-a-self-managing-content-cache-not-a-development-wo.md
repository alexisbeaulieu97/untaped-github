+++
schema = "untaped.orchestration.decision/v1"
id = "dec_019f68bd2fd7769f841b09dd5a9f6d94"
kind = "decision"
title = "The corpus is a self-managing content cache, not a development workspace"
created_at = "2026-07-12T13:22:03.000Z"
tags = []

[[evidence]]
relation = "tracked-by"
reference = "git:325f5c5f9ac3977838f46ab1555824e1d7746a2e:docs/decisions.md#sha256:b5cb8187398af4fee52b720c6890129f602c33d8c8c44c38b646c5b45d18f3ce"
+++

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
