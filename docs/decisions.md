# Architecture decisions

The canonical, typed decisions for this repository live in
`.untaped/orchestration/decisions/`. Humans can browse the generated
[decision view](../.untaped/orchestration/views/decisions.md); agents must start
with `untaped-orchestration brief --format json` and use CLI reads against the
returned IDs. Generated views are human navigation only and must not be edited
or used as canonical tool input.

This tool inherits the SDK-wide direction recorded in the core
[`untaped` decisions](https://github.com/alexisbeaulieu97/untaped/blob/main/docs/decisions.md).
The approved current sweep command and report contract remains in the
[sweep UX redesign spec](superpowers/specs/2026-07-10-sweep-ux-redesign-design.md).
The July 2 spec and July 6 implementation plan describe the superseded 0.14
surface and remain historical implementation context only.

Migration provenance is preserved in the gapless
[coverage manifest](orchestration-migration/coverage.toml), guarded
[import manifest](orchestration-migration/import.toml), planned independent
[review evidence](orchestration-migration/review.md), and
[historical input disposition](orchestration-migration/historical-inputs.toml).
The older five-decision pilot is classified only as
`superseded-by-current-source`; none of its store, record, or decision IDs is
canonical.
