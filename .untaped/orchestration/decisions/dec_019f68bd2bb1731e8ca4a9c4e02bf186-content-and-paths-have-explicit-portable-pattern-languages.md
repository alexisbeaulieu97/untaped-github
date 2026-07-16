+++
schema = "untaped.orchestration.decision/v1"
id = "dec_019f68bd2bb1731e8ca4a9c4e02bf186"
kind = "decision"
title = "Content and paths have explicit, portable pattern languages"
created_at = "2026-07-12T13:22:03.000Z"
tags = []

[[evidence]]
relation = "tracked-by"
reference = "git:325f5c5f9ac3977838f46ab1555824e1d7746a2e:docs/decisions.md#sha256:b5cb8187398af4fee52b720c6890129f602c33d8c8c44c38b646c5b45d18f3ce"
+++

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
