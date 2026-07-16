+++
schema = "untaped.orchestration.decision/v1"
id = "dec_019f68bd288376be90c3a91edf4de3ae"
kind = "decision"
title = "`sweep` is question-first over a local corpus; the corpus is the engine, not GitHub Search"
created_at = "2026-07-12T13:22:03.000Z"
tags = []

[[evidence]]
relation = "tracked-by"
reference = "git:325f5c5f9ac3977838f46ab1555824e1d7746a2e:docs/decisions.md#sha256:b5cb8187398af4fee52b720c6890129f602c33d8c8c44c38b646c5b45d18f3ce"
+++

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
