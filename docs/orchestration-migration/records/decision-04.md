
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
