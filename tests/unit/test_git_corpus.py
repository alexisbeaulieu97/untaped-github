"""Integration-style tests for the local Git corpus adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from untaped_github.domain import CorpusRepoTarget
from untaped_github.domain.errors import GitCorpusError
from untaped_github.infrastructure.git_corpus import GitCorpusCache


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _source_repo(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "a@example.com")
    _git(repo, "config", "user.name", "A")
    _git(repo, "config", "commit.gpgsign", "false")
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


def _item(full_name: str, source: Path) -> CorpusRepoTarget:
    return CorpusRepoTarget(
        full_name=full_name,
        clone_url=source.as_uri(),
        default_branch="main",
    )


def test_sync_fetches_blobful_default_branch_and_grep_parses_hits(tmp_path: Path) -> None:
    source = _source_repo(
        tmp_path,
        "source",
        {"actions.yml": "hello\nuses: acme/action@v1\n"},
    )
    cache = GitCorpusCache()
    root = tmp_path / "corpus"
    repo = _item("acme/api", source)

    synced = cache.sync_default_branch(repo, root=root, depth=1, auth_header=None)
    hits = cache.grep_default_branch(
        repo,
        root=root,
        pattern="acme/action",
        paths=(),
        globs=(),
        ignore_case=False,
        fixed_strings=False,
        word_regexp=False,
    )

    assert synced.repo == "acme/api"
    assert synced.ref == "main"
    assert synced.status == "synced"
    assert hits[0].model_dump() == {
        "repo": "acme/api",
        "ref": "main",
        "path": "actions.yml",
        "line": 2,
        "column": 7,
        "text": "uses: acme/action@v1",
    }


def test_grep_exit_one_is_successful_no_match(tmp_path: Path) -> None:
    source = _source_repo(tmp_path, "source", {"README.md": "nothing here\n"})
    cache = GitCorpusCache()
    root = tmp_path / "corpus"
    repo = _item("acme/api", source)
    cache.sync_default_branch(repo, root=root, depth=1, auth_header=None)

    hits = cache.grep_default_branch(
        repo,
        root=root,
        pattern="acme/action",
        paths=(),
        globs=(),
        ignore_case=False,
        fixed_strings=False,
        word_regexp=False,
    )

    assert hits == ()


def test_grep_exit_above_one_is_failure(tmp_path: Path) -> None:
    source = _source_repo(tmp_path, "source", {"README.md": "nothing here\n"})
    cache = GitCorpusCache()
    root = tmp_path / "corpus"
    repo = _item("acme/api", source)
    cache.sync_default_branch(repo, root=root, depth=1, auth_header=None)

    with pytest.raises(GitCorpusError, match="brackets"):
        cache.grep_default_branch(
            repo,
            root=root,
            pattern="[",
            paths=(),
            globs=(),
            ignore_case=False,
            fixed_strings=False,
            word_regexp=False,
        )


def test_grep_handles_colons_in_paths(tmp_path: Path) -> None:
    source = _source_repo(tmp_path, "source", {"a:b.txt": "uses: acme/action@v1\n"})
    cache = GitCorpusCache()
    root = tmp_path / "corpus"
    repo = _item("acme/api", source)
    cache.sync_default_branch(repo, root=root, depth=1, auth_header=None)

    [hit] = cache.grep_default_branch(
        repo,
        root=root,
        pattern="acme/action",
        paths=(),
        globs=(),
        ignore_case=False,
        fixed_strings=False,
        word_regexp=False,
    )

    assert hit.path == "a:b.txt"
    assert hit.column == 7


def test_list_clean_and_worktree_are_confined_to_managed_root(tmp_path: Path) -> None:
    source = _source_repo(tmp_path, "source", {"README.md": "uses: acme/action@v1\n"})
    cache = GitCorpusCache()
    root = tmp_path / "corpus"
    repo = _item("acme/api", source)
    cache.sync_default_branch(repo, root=root, depth=1, auth_header=None)

    [listed] = cache.list_repos(root=root)
    worktree = cache.materialize_worktree(repo, root=root, ref=None)
    [cleaned] = cache.clean_repos(root=root, repos=("acme/api",))

    assert listed.repo == "acme/api"
    assert listed.path.startswith(str(root))
    assert (Path(worktree.path) / "README.md").is_file()
    assert cleaned.status == "removed"
    assert cache.list_repos(root=root) == ()
