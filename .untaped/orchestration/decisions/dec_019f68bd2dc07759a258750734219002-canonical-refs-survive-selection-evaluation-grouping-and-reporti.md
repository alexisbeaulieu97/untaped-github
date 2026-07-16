+++
schema = "untaped.orchestration.decision/v1"
id = "dec_019f68bd2dc07759a258750734219002"
kind = "decision"
title = "Canonical refs survive selection, evaluation, grouping, and reporting"
created_at = "2026-07-12T13:22:03.000Z"
tags = []

[[evidence]]
relation = "tracked-by"
reference = "git:325f5c5f9ac3977838f46ab1555824e1d7746a2e:docs/decisions.md#sha256:b5cb8187398af4fee52b720c6890129f602c33d8c8c44c38b646c5b45d18f3ce"
+++

Refs remain fully qualified (`refs/heads/main`, `refs/tags/main`) from local
enumeration through serialization. A same-named branch and tag are distinct;
shortening them would corrupt provenance and can combine evidence from
different histories.

Content evidence groups refs only when blob identity, path, range, and content
are identical. Path evidence groups by path. Constraints are evaluated before
grouping and on the same ref as the primary evidence, so grouping cannot make a
cross-ref constraint appear satisfied.
