
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
