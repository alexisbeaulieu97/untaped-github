
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
