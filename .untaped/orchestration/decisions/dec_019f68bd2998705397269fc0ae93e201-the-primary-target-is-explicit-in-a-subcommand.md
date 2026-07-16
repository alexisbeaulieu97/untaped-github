+++
schema = "untaped.orchestration.decision/v1"
id = "dec_019f68bd2998705397269fc0ae93e201"
kind = "decision"
title = "The primary target is explicit in a subcommand"
created_at = "2026-07-12T13:22:03.000Z"
tags = []

[[evidence]]
relation = "tracked-by"
reference = "git:325f5c5f9ac3977838f46ab1555824e1d7746a2e:docs/decisions.md#sha256:b5cb8187398af4fee52b720c6890129f602c33d8c8c44c38b646c5b45d18f3ce"
+++

The public entrypoints are `sweep content REGEX` and `sweep paths GLOB`. The
required positional value is the primary target and is the sole source of
reported match evidence.

This replaces the root command's parallel `--grep`, `--not-grep`,
`--has-file`, and `--lacks-file` collections. Those options forced the renderer
to treat every predicate as equally reportable even when the user wanted one
answer qualified by supporting conditions. An explicit target gives help,
validation, table columns, and evidence one unambiguous shape. There are no
compatibility aliases; old syntax fails with a migration-oriented error.
