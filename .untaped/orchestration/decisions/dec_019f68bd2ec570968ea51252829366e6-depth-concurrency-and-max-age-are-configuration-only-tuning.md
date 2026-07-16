+++
schema = "untaped.orchestration.decision/v1"
id = "dec_019f68bd2ec570968ea51252829366e6"
kind = "decision"
title = "Depth, concurrency, and max age are configuration-only tuning"
created_at = "2026-07-12T13:22:03.000Z"
tags = []

[[evidence]]
relation = "tracked-by"
reference = "git:325f5c5f9ac3977838f46ab1555824e1d7746a2e:docs/decisions.md#sha256:b5cb8187398af4fee52b720c6890129f602c33d8c8c44c38b646c5b45d18f3ce"
+++

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
