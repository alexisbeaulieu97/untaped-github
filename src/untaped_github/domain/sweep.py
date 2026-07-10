"""Pure domain contracts for sweep questions, evaluation, and reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

RefProfile = Literal["default", "branches", "tags", "all"]
ContentMode = Literal["extended_regex", "fixed_strings"]
SweepFreshness = Literal["auto", "refresh", "cached"]
ConstraintKind = Literal["with_content", "without_content", "with_path", "without_path"]
FailureStage = Literal["prepare", "scan"]


def _reject_actual_newline(pattern: str) -> None:
    if "\n" in pattern or "\r" in pattern:
        raise ValueError(f"pattern contains an actual newline: {pattern!r}")


@dataclass(frozen=True)
class RefSelector:
    """Selected ref profile plus explicit ref globs."""

    profile: RefProfile = "default"
    globs: tuple[str, ...] = ()

    def beyond_default(self) -> bool:
        return self.profile != "default" or bool(self.globs)

    def to_dict(self) -> dict[str, object]:
        return {"profile": self.profile, "globs": list(self.globs)}


@dataclass(frozen=True)
class SweepScope:
    """Normalized effective repository scope."""

    orgs: tuple[str, ...] = ()
    teams: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    stdin: bool = False
    include_archived: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "orgs": list(self.orgs),
            "teams": list(self.teams),
            "repos": list(self.repos),
            "stdin": self.stdin,
            "include_archived": self.include_archived,
        }


@dataclass(frozen=True)
class ContentQuestion:
    """Primary content matcher whose hits become report evidence."""

    pattern: str
    kind: Literal["content"] = field(default="content", init=False)

    def __post_init__(self) -> None:
        _reject_actual_newline(self.pattern)

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "pattern": self.pattern}


@dataclass(frozen=True)
class PathQuestion:
    """Primary path matcher whose hits become report evidence."""

    pattern: str
    kind: Literal["path"] = field(default="path", init=False)

    def __post_init__(self) -> None:
        _reject_actual_newline(self.pattern)

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "pattern": self.pattern}


type SweepQuestion = ContentQuestion | PathQuestion


@dataclass(frozen=True)
class ContentConstraint:
    """A required or forbidden content occurrence on the primary evidence ref."""

    kind: Literal["with_content", "without_content"]
    pattern: str

    def __post_init__(self) -> None:
        if self.kind not in ("with_content", "without_content"):
            raise ValueError(f"invalid content constraint kind: {self.kind!r}")
        _reject_actual_newline(self.pattern)

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "pattern": self.pattern}


@dataclass(frozen=True)
class PathConstraint:
    """A required or forbidden path occurrence on the primary evidence ref."""

    kind: Literal["with_path", "without_path"]
    pattern: str

    def __post_init__(self) -> None:
        if self.kind not in ("with_path", "without_path"):
            raise ValueError(f"invalid path constraint kind: {self.kind!r}")
        _reject_actual_newline(self.pattern)

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "pattern": self.pattern}


type SweepConstraint = ContentConstraint | PathConstraint


@dataclass(frozen=True)
class ContentOptions:
    """Invocation-wide matching options shared by all content patterns."""

    mode: ContentMode = "extended_regex"
    ignore_case: bool = False
    word_regexp: bool = False

    def __post_init__(self) -> None:
        if self.mode not in ("extended_regex", "fixed_strings"):
            raise ValueError(f"invalid content mode: {self.mode!r}")

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "ignore_case": self.ignore_case,
            "word_regexp": self.word_regexp,
        }


@dataclass(frozen=True)
class PathFilters:
    """Ordered include/exclude filters applied only to content evaluation."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for pattern in (*self.include, *self.exclude):
            _reject_actual_newline(pattern)

    def to_dict(self) -> dict[str, object]:
        return {"include": list(self.include), "exclude": list(self.exclude)}


@dataclass(frozen=True)
class SweepQuery:
    """Normalized effective sweep question, including invocation defaults."""

    scope: SweepScope
    question: SweepQuestion
    constraints: tuple[SweepConstraint, ...] = ()
    content_options: ContentOptions = field(default_factory=ContentOptions)
    path_filters: PathFilters = field(default_factory=PathFilters)
    refs: RefSelector = field(default_factory=RefSelector)
    freshness: SweepFreshness = "auto"
    context: int = 0

    def __post_init__(self) -> None:
        if self.freshness not in ("auto", "refresh", "cached"):
            raise ValueError(f"invalid freshness: {self.freshness!r}")
        if self.context < 0:
            raise ValueError("context must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope.to_dict(),
            "question": self.question.to_dict(),
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "content_options": self.content_options.to_dict(),
            "path_filters": self.path_filters.to_dict(),
            "refs": self.refs.to_dict(),
            "freshness": self.freshness,
            "context": self.context,
        }


@dataclass(frozen=True)
class RefEvaluation:
    """Primary and ordered constraint hit counts for one canonical ref."""

    ref: str
    question_hits: int
    constraint_hits: tuple[int, ...] = ()


def ref_matches(query: SweepQuery, evaluation: RefEvaluation) -> bool:
    """Return whether one ref satisfies the primary and every constraint."""
    if len(evaluation.constraint_hits) != len(query.constraints):
        raise ValueError("constraint hit count must match query constraints")
    if evaluation.question_hits <= 0:
        return False
    return all(
        hits > 0 if constraint.kind in ("with_content", "with_path") else hits == 0
        for constraint, hits in zip(query.constraints, evaluation.constraint_hits, strict=True)
    )


@dataclass(frozen=True)
class MatchContext:
    """Inclusive source range surrounding a content match."""

    start_line: int
    end_line: int
    content: str

    def to_dict(self) -> dict[str, object]:
        return {
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
        }


@dataclass(frozen=True)
class ContentMatch:
    """One grouped content-evidence range across canonical refs."""

    refs: tuple[str, ...]
    path: str
    start_line: int
    end_line: int
    content: str
    context: MatchContext | None = None
    kind: Literal["content"] = field(default="content", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "refs", tuple(sorted(set(self.refs))))

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "kind": self.kind,
            "refs": list(self.refs),
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
        }
        if self.context is not None:
            value["context"] = self.context.to_dict()
        return value


@dataclass(frozen=True)
class PathMatch:
    """One grouped path-evidence item across canonical refs."""

    refs: tuple[str, ...]
    path: str
    kind: Literal["path"] = field(default="path", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "refs", tuple(sorted(set(self.refs))))

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "refs": list(self.refs), "path": self.path}


type SweepMatch = ContentMatch | PathMatch


def _match_sort_key(match: SweepMatch) -> tuple[str, str, int, int, str, tuple[str, ...]]:
    if isinstance(match, ContentMatch):
        return (
            match.kind,
            match.path,
            match.start_line,
            match.end_line,
            match.content,
            match.refs,
        )
    return (match.kind, match.path, -1, -1, "", match.refs)


@dataclass(frozen=True)
class SweepResult:
    """All retained primary evidence for one matching repository."""

    full_name: str
    clone_url: str | None
    refs_matched: tuple[str, ...]
    matches: tuple[SweepMatch, ...]
    owners: tuple[str, ...]
    synced_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "refs_matched", tuple(sorted(set(self.refs_matched))))
        object.__setattr__(self, "matches", tuple(sorted(self.matches, key=_match_sort_key)))
        object.__setattr__(self, "owners", tuple(sorted(set(self.owners))))

    def to_dict(self) -> dict[str, object]:
        return {
            "full_name": self.full_name,
            "clone_url": self.clone_url,
            "refs_matched": list(self.refs_matched),
            "matches": [match.to_dict() for match in self.matches],
            "owners": list(self.owners),
            "synced_at": self.synced_at.isoformat() if self.synced_at is not None else None,
        }


@dataclass(frozen=True)
class SweepFailure:
    """One repository that could not be scanned."""

    full_name: str
    stage: FailureStage
    reason: str

    def __post_init__(self) -> None:
        if self.stage not in ("prepare", "scan"):
            raise ValueError(f"invalid failure stage: {self.stage!r}")

    def to_dict(self) -> dict[str, object]:
        return {"full_name": self.full_name, "stage": self.stage, "reason": self.reason}


@dataclass(frozen=True)
class SweepSummary:
    """Coverage and freshness accounting for one sweep."""

    selected: int
    prepared: int
    scanned: int
    matched: int
    unscanned: int
    refreshed: int
    cached: int
    oldest_fetched_at: datetime | None = None

    def __post_init__(self) -> None:
        values = (
            self.selected,
            self.prepared,
            self.scanned,
            self.matched,
            self.unscanned,
            self.refreshed,
            self.cached,
        )
        if any(value < 0 for value in values):
            raise ValueError("summary counts must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "selected": self.selected,
            "prepared": self.prepared,
            "scanned": self.scanned,
            "matched": self.matched,
            "unscanned": self.unscanned,
            "refreshed": self.refreshed,
            "cached": self.cached,
            "oldest_fetched_at": (
                self.oldest_fetched_at.isoformat() if self.oldest_fetched_at is not None else None
            ),
        }


@dataclass(frozen=True)
class SweepReport:
    """Complete archival sweep report."""

    query: SweepQuery
    results: tuple[SweepResult, ...]
    failures: tuple[SweepFailure, ...]
    summary: SweepSummary

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "results",
            tuple(sorted(self.results, key=lambda row: row.full_name)),
        )
        object.__setattr__(
            self,
            "failures",
            tuple(sorted(self.failures, key=lambda failure: failure.full_name)),
        )
        prepare_failures = sum(failure.stage == "prepare" for failure in self.failures)
        scan_failures = sum(failure.stage == "scan" for failure in self.failures)
        if self.summary.prepared + prepare_failures != self.summary.selected:
            raise ValueError("prepared plus prepare failures must equal selected")
        if self.summary.scanned + scan_failures != self.summary.prepared:
            raise ValueError("scanned plus scan failures must equal prepared")
        if self.summary.unscanned != len(self.failures):
            raise ValueError("unscanned must equal failure count")
        if self.summary.matched != len(self.results):
            raise ValueError("matched must equal result count")
        if self.summary.refreshed + self.summary.cached != self.summary.prepared:
            raise ValueError("refreshed plus cached must equal prepared")

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query.to_dict(),
            "results": [result.to_dict() for result in self.results],
            "failures": [failure.to_dict() for failure in self.failures],
            "summary": self.summary.to_dict(),
        }


# Transitional row shape consumed by the pre-redesign application use case.
@dataclass(frozen=True)
class RepoSweepOutcome:
    full_name: str
    clone_url: str | None
    matched: bool
    refs_matched: tuple[str, ...]
    hits: Mapping[str, int]
    owners: tuple[str, ...]
    synced_at: str | None


def profile_join(stored: RefProfile, requested: RefProfile) -> RefProfile:
    """Return the widening join of two corpus fetch profiles."""
    if stored == requested:
        return stored
    if stored == "all" or requested == "all":
        return "all"
    if stored == "default":
        return requested
    if requested == "default":
        return stored
    return "all"
