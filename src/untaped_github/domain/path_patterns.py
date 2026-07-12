"""Portable gitignore-style path matching for sweep questions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from pathspec import PathSpec
from pathspec.pattern import Pattern
from pathspec.patterns.gitignore import GitIgnorePatternError


@dataclass(frozen=True)
class PathPattern:
    """One validated public path pattern backed only by PathSpec semantics."""

    pattern: str
    _spec: PathSpec[Pattern] = field(repr=False, compare=False)

    @classmethod
    def compile(cls, pattern: str, *, option: str) -> PathPattern:
        """Compile one user pattern and attach its option to validation errors."""
        prefix = f"{option} {pattern!r}"
        if "\n" in pattern or "\r" in pattern:
            raise ValueError(f"{prefix}: path pattern contains an actual newline")
        if pattern.startswith("!"):
            raise ValueError(f"{prefix}: unescaped leading '!' is not allowed")
        if pattern.startswith("#"):
            raise ValueError(f"{prefix}: comment-only path pattern is not allowed")
        try:
            spec = PathSpec.from_lines("gitignore", [pattern])
        except GitIgnorePatternError as exc:
            raise ValueError(f"{prefix}: invalid path pattern: {exc}") from exc
        return cls(pattern=pattern, _spec=spec)

    def matches(self, path: str) -> bool:
        """Return whether the repository-relative path matches this pattern."""
        return self._spec.match_file(path)

    def matching(self, paths: Iterable[str]) -> tuple[str, ...]:
        """Return matching paths in their original order."""
        return tuple(path for path in paths if self.matches(path))


@dataclass(frozen=True)
class ContentPathFilter:
    """Include/exclude filter shared by every content matcher in a sweep."""

    include: tuple[PathPattern, ...]
    exclude: tuple[PathPattern, ...]

    @classmethod
    def compile(
        cls,
        *,
        include: Iterable[str],
        exclude: Iterable[str],
    ) -> ContentPathFilter:
        """Compile ordered content path filters with option-aware errors."""
        return cls(
            include=tuple(
                PathPattern.compile(pattern, option="--include-path") for pattern in include
            ),
            exclude=tuple(
                PathPattern.compile(pattern, option="--exclude-path") for pattern in exclude
            ),
        )

    def matches(self, path: str) -> bool:
        """Apply include union followed by exclusion-wins semantics."""
        included = not self.include or any(pattern.matches(path) for pattern in self.include)
        excluded = any(pattern.matches(path) for pattern in self.exclude)
        return included and not excluded

    def matching(self, paths: Iterable[str]) -> tuple[str, ...]:
        """Return eligible content paths in their original order."""
        return tuple(path for path in paths if self.matches(path))
