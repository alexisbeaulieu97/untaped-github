+++
schema = "untaped.orchestration.decision/v1"
id = "dec_019f68bd2aa2734a8cd98a5d349d7126"
kind = "decision"
title = "One primary question plus conjunctive same-ref constraints — no boolean mode"
created_at = "2026-07-12T13:22:03.000Z"
tags = []

[[evidence]]
relation = "tracked-by"
reference = "git:325f5c5f9ac3977838f46ab1555824e1d7746a2e:docs/decisions.md#sha256:b5cb8187398af4fee52b720c6890129f602c33d8c8c44c38b646c5b45d18f3ce"
+++

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
