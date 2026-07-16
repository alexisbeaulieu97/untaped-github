
The local Git adapter (`GitCorpusCache`) never lets a subprocess inherit the
CLI's stdio. Its `stdout` is a pipe when the caller captures output and
`DEVNULL` otherwise; its `stderr` is always a pipe.

A subprocess that inherits stdio writes straight into the CLI's own stdout, so
a first-time sweep's `git init`/fetch chatter leaked into `--format pipe` and
`--format raw` streams and corrupted machine-readable output. Capturing
`stderr` rather than discarding it also means a failed Git call surfaces the
real Git error instead of a bare nonzero exit.

The durable lesson: a test that asserts a subprocess "keeps existing
behavior" by locking stdio inheritance is a smell. Subprocess adapters isolate
their stdio by default.
