from __future__ import annotations

import re
from pathlib import Path

import pytest
from untaped.api import ConfigError

from untaped_github.application.sweep_matching import compile_sweep_matchers
from untaped_github.domain import (
    ContentConstraint,
    ContentOptions,
    ContentQuestion,
    GrepHit,
    PathConstraint,
    PathFilters,
    PathQuestion,
    SweepQuery,
    SweepScope,
)


class _Corpus:
    def __init__(self, errors: dict[str, str] | None = None) -> None:
        self.errors = errors or {}
        self.validated: list[tuple[str, bool]] = []

    def validate_pattern(
        self,
        *,
        root: Path,
        pattern: str,
        fixed_strings: bool,
    ) -> str | None:
        self.validated.append((pattern, fixed_strings))
        return self.errors.get(pattern)


def test_compile_validates_content_and_filters_returned_hits(tmp_path: Path) -> None:
    corpus = _Corpus()
    query = SweepQuery(
        scope=SweepScope(orgs=("acme",)),
        question=ContentQuestion(pattern="TODO|FIXME"),
        constraints=(
            ContentConstraint(kind="without_content", pattern="DONE"),
            PathConstraint(kind="with_path", pattern="Jenkinsfile"),
        ),
        content_options=ContentOptions(mode="extended_regex"),
        path_filters=PathFilters(include=("src/**",), exclude=("src/vendor/**",)),
    )

    matchers = compile_sweep_matchers(query, corpus=corpus, root=tmp_path / "corpus")
    hits = (
        GrepHit(path="README.md", line=1, text="TODO", blob_oid="one"),
        GrepHit(path="src/app.py", line=2, text="TODO", blob_oid="two"),
        GrepHit(path="src/vendor/app.py", line=3, text="TODO", blob_oid="three"),
    )

    assert corpus.validated == [("TODO|FIXME", False), ("DONE", False)]
    assert matchers.filter_content_hits(hits) == (hits[1],)
    assert matchers.matching_constraint_paths(1, ("Jenkinsfile", "nested/Jenkinsfile")) == (
        "Jenkinsfile",
        "nested/Jenkinsfile",
    )


def test_path_question_and_constraint_use_compiled_pathspecs(tmp_path: Path) -> None:
    query = SweepQuery(
        scope=SweepScope(orgs=("acme",)),
        question=PathQuestion(pattern="/Jenkinsfile"),
        constraints=(PathConstraint(kind="without_path", pattern=".github/**"),),
    )

    matchers = compile_sweep_matchers(query, corpus=_Corpus(), root=tmp_path / "corpus")
    tree = ("Jenkinsfile", "nested/Jenkinsfile", ".github/workflows/ci.yml")

    assert matchers.matching_question_paths(tree) == ("Jenkinsfile",)
    assert matchers.matching_constraint_paths(0, tree) == (".github/workflows/ci.yml",)


def test_compile_reports_content_option_and_pattern(tmp_path: Path) -> None:
    query = SweepQuery(
        scope=SweepScope(orgs=("acme",)),
        question=ContentQuestion(pattern="["),
    )

    with pytest.raises(ConfigError, match=r"content REGEX '\[': invalid regular expression"):
        compile_sweep_matchers(
            query,
            corpus=_Corpus({"[": "invalid regular expression"}),
            root=tmp_path / "corpus",
        )


def test_compile_validates_every_path_pattern_with_its_public_option(tmp_path: Path) -> None:
    query = SweepQuery(
        scope=SweepScope(orgs=("acme",)),
        question=PathQuestion(pattern="README.md"),
        constraints=(PathConstraint(kind="with_path", pattern="!vendor/**"),),
    )

    with pytest.raises(
        ConfigError,
        match=r"--with-path '!vendor/\*\*'.*leading '!'",
    ):
        compile_sweep_matchers(query, corpus=_Corpus(), root=tmp_path / "corpus")


def test_fixed_string_mode_reaches_every_content_validation(tmp_path: Path) -> None:
    corpus = _Corpus()
    query = SweepQuery(
        scope=SweepScope(orgs=("acme",)),
        question=PathQuestion(pattern="README.md"),
        constraints=(ContentConstraint(kind="with_content", pattern="[literal"),),
        content_options=ContentOptions(mode="fixed_strings"),
    )

    compile_sweep_matchers(query, corpus=corpus, root=tmp_path / "corpus")

    assert corpus.validated == [("[literal", True)]


@pytest.mark.parametrize("mode", ["extended_regex", "fixed_strings"])
@pytest.mark.parametrize("pattern", ["first\nsecond", "first\rsecond"])
@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("content REGEX", "question"),
        ("--with-content", "with_content"),
        ("--without-content", "without_content"),
    ],
)
def test_compile_rejects_actual_newlines_before_corpus_validation(
    tmp_path: Path,
    mode: str,
    pattern: str,
    source: str,
    kind: str,
) -> None:
    if kind == "question":
        question = ContentQuestion(pattern="safe")
        object.__setattr__(question, "pattern", pattern)
        constraints: tuple[ContentConstraint, ...] = ()
    else:
        question = PathQuestion(pattern="README.md")
        constraint = ContentConstraint(kind=kind, pattern="safe")  # type: ignore[arg-type]
        object.__setattr__(constraint, "pattern", pattern)
        constraints = (constraint,)
    query = SweepQuery(
        scope=SweepScope(orgs=("acme",)),
        question=question,
        constraints=constraints,
        content_options=ContentOptions(mode=mode),  # type: ignore[arg-type]
    )
    corpus = _Corpus()

    with pytest.raises(
        ConfigError,
        match=rf"{re.escape(source)} {re.escape(repr(pattern))}:.*actual newline",
    ):
        compile_sweep_matchers(query, corpus=corpus, root=tmp_path / "corpus")

    assert corpus.validated == []
