
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
