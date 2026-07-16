+++
schema = "untaped.orchestration.decision/v1"
id = "dec_019f68bd30df76bcaa23ac2ea45728cb"
kind = "decision"
title = "Fleet-standard exit codes use explicit match and completeness gates"
created_at = "2026-07-12T13:22:03.000Z"
tags = []

[[evidence]]
relation = "tracked-by"
reference = "git:325f5c5f9ac3977838f46ab1555824e1d7746a2e:docs/decisions.md#sha256:b5cb8187398af4fee52b720c6890129f602c33d8c8c44c38b646c5b45d18f3ce"
+++

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
