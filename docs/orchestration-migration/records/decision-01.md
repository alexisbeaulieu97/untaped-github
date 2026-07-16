
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
