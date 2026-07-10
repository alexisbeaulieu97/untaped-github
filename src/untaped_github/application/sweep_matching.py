"""Compile and apply the portable matchers used by sweep orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from untaped.api import ConfigError

from untaped_github.domain import (
    ContentConstraint,
    ContentQuestion,
    GrepHit,
    PathConstraint,
    PathQuestion,
    SweepQuery,
)
from untaped_github.domain.path_patterns import ContentPathFilter, PathPattern


class ContentPatternValidator(Protocol):
    """Narrow corpus contract needed for up-front content validation."""

    def validate_pattern(
        self,
        *,
        root: Path,
        pattern: str,
        fixed_strings: bool,
    ) -> str | None: ...


@dataclass(frozen=True)
class SweepMatchers:
    """Validated matchers shared by every repository and selected ref."""

    question_path: PathPattern | None
    constraint_paths: tuple[PathPattern | None, ...]
    content_paths: ContentPathFilter

    def filter_content_hits(self, hits: Iterable[GrepHit]) -> tuple[GrepHit, ...]:
        """Apply public path filters after Git has returned all content hits."""
        return tuple(hit for hit in hits if self.content_paths.matches(hit.path))

    def matching_question_paths(self, paths: Iterable[str]) -> tuple[str, ...]:
        """Return primary path evidence from one tree."""
        if self.question_path is None:
            raise ValueError("content questions do not have a path matcher")
        return self.question_path.matching(paths)

    def matching_constraint_paths(
        self,
        index: int,
        paths: Iterable[str],
    ) -> tuple[str, ...]:
        """Return witnesses for one path constraint from one tree."""
        matcher = self.constraint_paths[index]
        if matcher is None:
            raise ValueError("content constraints do not have a path matcher")
        return matcher.matching(paths)


def compile_sweep_matchers(
    query: SweepQuery,
    *,
    corpus: ContentPatternValidator,
    root: Path,
) -> SweepMatchers:
    """Validate every public matcher before any corpus refresh can begin."""
    fixed_strings = query.content_options.mode == "fixed_strings"
    content_patterns: list[tuple[str, str]] = []
    if isinstance(query.question, ContentQuestion):
        content_patterns.append(("REGEX", query.question.pattern))
    content_patterns.extend(
        (f"--{constraint.kind.replace('_', '-')}", constraint.pattern)
        for constraint in query.constraints
        if isinstance(constraint, ContentConstraint)
    )
    for option, pattern in content_patterns:
        error = corpus.validate_pattern(
            root=root,
            pattern=pattern,
            fixed_strings=fixed_strings,
        )
        if error is not None:
            raise ConfigError(f"{option} {pattern!r}: {error}")

    question_path = (
        _compile_path(query.question.pattern, option="GLOB")
        if isinstance(query.question, PathQuestion)
        else None
    )
    constraint_paths = tuple(
        _compile_path(
            constraint.pattern,
            option=f"--{constraint.kind.replace('_', '-')}",
        )
        if isinstance(constraint, PathConstraint)
        else None
        for constraint in query.constraints
    )
    try:
        content_paths = ContentPathFilter.compile(
            include=query.path_filters.include,
            exclude=query.path_filters.exclude,
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return SweepMatchers(
        question_path=question_path,
        constraint_paths=constraint_paths,
        content_paths=content_paths,
    )


def _compile_path(pattern: str, *, option: str) -> PathPattern:
    try:
        return PathPattern.compile(pattern, option=option)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
