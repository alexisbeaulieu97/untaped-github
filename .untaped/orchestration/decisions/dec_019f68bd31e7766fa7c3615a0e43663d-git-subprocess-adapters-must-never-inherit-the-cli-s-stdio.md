+++
schema = "untaped.orchestration.decision/v1"
id = "dec_019f68bd31e7766fa7c3615a0e43663d"
kind = "decision"
title = "Git subprocess adapters must never inherit the CLI's stdio"
created_at = "2026-07-12T13:22:03.000Z"
tags = []

[[evidence]]
relation = "tracked-by"
reference = "git:325f5c5f9ac3977838f46ab1555824e1d7746a2e:docs/decisions.md#sha256:b5cb8187398af4fee52b720c6890129f602c33d8c8c44c38b646c5b45d18f3ce"
+++

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
