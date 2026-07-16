
The public entrypoints are `sweep content REGEX` and `sweep paths GLOB`. The
required positional value is the primary target and is the sole source of
reported match evidence.

This replaces the root command's parallel `--grep`, `--not-grep`,
`--has-file`, and `--lacks-file` collections. Those options forced the renderer
to treat every predicate as equally reportable even when the user wanted one
answer qualified by supporting conditions. An explicit target gives help,
validation, table columns, and evidence one unambiguous shape. There are no
compatibility aliases; old syntax fails with a migration-oriented error.
