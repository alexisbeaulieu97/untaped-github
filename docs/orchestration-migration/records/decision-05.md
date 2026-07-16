
JSON and YAML serialize one `{query, results, failures, summary}` report.
Each result contains the repository, canonical matched refs, primary matches,
owners, and freshness. Failures retain their `prepare` or `scan` stage, and the
summary retains selection and coverage accounting. A JSON/YAML column
projection always retains `full_name` and `refs_matched` for result identity,
while query, failures, and summary remain complete.

Table output has one row per primary match. Raw output keeps one repository row
so it can feed other tools without accidental duplicates. Pipe output emits
complete `github.sweep_result` records and ignores `--columns`; a projection
must never make a record unusable as the scope for another sweep. This replaces
the old `--show repos|matches` split and the separate `github.sweep_repo` and
`github.sweep_match` kinds. Table projection always keeps repository and ref
identity. Raw columns are intentionally lossy and custom.

Raw and pipe stdout remain matching-result projections, not archival reports.
Every run writes its summary and each unscanned failure to stderr, including an
otherwise empty, successful raw/pipe run. JSON/YAML are the archival formats.
This split keeps pipelines data-only without hiding coverage from the operator;
`--require-complete` is the explicit machine gate for any unscanned repository.

CODEOWNERS is resolved per qualifying ref and primary-evidence path. The result
stores a lexically sorted owner union, and table output repeats that union on
each match row. This intentionally favors a concise "who do I ping?" result
over a ref/path provenance mapping. Constraint witnesses do not affect owners.

Requested scope lists, constraints, filters, and ref globs preserve CLI order.
Results and failures sort by `full_name`; canonical refs and owners sort
lexically. Matches sort by kind, path, start line, end line, content, and the
sorted canonical refs tuple; path matches omit the inapplicable line and
content fields but still use refs as the final tie-breaker. Context remains in
source-line order. Stable ordering makes reports reproducible while preserving
the user's stated query.
