from __future__ import annotations

import pytest

from untaped_github.domain.path_patterns import ContentPathFilter, PathPattern


@pytest.mark.parametrize(
    ("pattern", "matching", "not_matching"),
    [
        ("Jenkinsfile", ("Jenkinsfile", "services/api/Jenkinsfile"), ("Jenkinsfile.old",)),
        ("/Jenkinsfile", ("Jenkinsfile",), ("services/api/Jenkinsfile",)),
        (".github/**", (".github/workflows/ci.yml",), ("nested/.github/workflows/ci.yml",)),
        (
            "**/.github/**",
            (".github/workflows/ci.yml", "nested/.github/workflows/ci.yml"),
            ("nested/github/workflows/ci.yml",),
        ),
        ("**/*.py", ("main.py", "src/main.py"), ("src/main.pyc",)),
    ],
)
def test_path_pattern_uses_gitignore_semantics(
    pattern: str,
    matching: tuple[str, ...],
    not_matching: tuple[str, ...],
) -> None:
    matcher = PathPattern.compile(pattern, option="--with-path")

    assert matcher.matching((*matching, *not_matching)) == matching


def test_escaped_leading_markers_are_literal() -> None:
    bang = PathPattern.compile(r"\!important", option="--with-path")
    hash_mark = PathPattern.compile(r"\#generated", option="--with-path")

    assert bang.matches("docs/!important")
    assert hash_mark.matches("#generated")


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("!vendor/**", r"--exclude-path '!vendor/\*\*'.*leading '!'"),
        ("# explanation", r"--include-path '# explanation'.*comment-only"),
        ("trailing\\", r"--with-path 'trailing\\\\'.*invalid path pattern"),
        ("src\n**", r"--with-path 'src\\n\*\*'.*actual newline"),
    ],
)
def test_invalid_path_patterns_have_user_ready_errors(pattern: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        PathPattern.compile(
            pattern,
            option="--exclude-path"
            if pattern.startswith("!")
            else ("--include-path" if pattern.startswith("#") else "--with-path"),
        )


def test_content_path_filter_includes_union_and_exclusion_wins() -> None:
    matcher = ContentPathFilter.compile(
        include=("src/**", "lib/**"),
        exclude=("src/vendor/**", "**/*.generated.py"),
    )

    assert matcher.matching(
        (
            "README.md",
            "src/app.py",
            "src/vendor/app.py",
            "lib/client.py",
            "lib/client.generated.py",
        )
    ) == ("src/app.py", "lib/client.py")


def test_content_path_filter_without_includes_starts_from_all_paths() -> None:
    matcher = ContentPathFilter.compile(include=(), exclude=(".github/**",))

    assert matcher.matching(("README.md", ".github/workflows/ci.yml")) == ("README.md",)
