
Refs remain fully qualified (`refs/heads/main`, `refs/tags/main`) from local
enumeration through serialization. A same-named branch and tag are distinct;
shortening them would corrupt provenance and can combine evidence from
different histories.

Content evidence groups refs only when blob identity, path, range, and content
are identical. Path evidence groups by path. Constraints are evaluated before
grouping and on the same ref as the primary evidence, so grouping cannot make a
cross-ref constraint appear satisfied.
