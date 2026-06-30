"""Integration-style tests for the local Git corpus adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from untaped_github.domain import CorpusRepoTarget
from untaped_github.domain.errors import GitCorpusError
from untaped_github.infrastructure.git_corpus import GitCorpusCache, _auth_config_env, _redact


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


def _source_repo(tmp_path: Path, name: str, files: dict[str, str | bytes]) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "a@example.com")
    _git(repo, "config", "user.name", "A")
    _git(repo, "config", "commit.gpgsign", "false")
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
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
        {
            "actions.yml": "hello\nuses: acme/action@v1\nsecond uses: acme/action@v2\n",
            "nested/workflow.yml": "uses: acme/action@v3\n",
        },
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
    assert [hit.model_dump() for hit in hits] == [
        {
            "repo": "acme/api",
            "ref": "main",
            "path": "actions.yml",
            "line": 2,
            "column": 7,
            "text": "uses: acme/action@v1",
        },
        {
            "repo": "acme/api",
            "ref": "main",
            "path": "actions.yml",
            "line": 3,
            "column": 14,
            "text": "second uses: acme/action@v2",
        },
        {
            "repo": "acme/api",
            "ref": "main",
            "path": "nested/workflow.yml",
            "line": 1,
            "column": 7,
            "text": "uses: acme/action@v3",
        },
    ]


def test_grep_skips_binary_files_and_keeps_text_hits(tmp_path: Path) -> None:
    source = _source_repo(
        tmp_path,
        "source",
        {
            "README.md": "uses: acme/action@v1\n",
            "asset.bin": b"\x00uses: acme/action@binary\x00",
        },
    )
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

    assert [hit.path for hit in hits] == ["README.md"]


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

    with pytest.raises(GitCorpusError, match=r"regular expression|brackets"):
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


def test_grep_malformed_output_is_git_corpus_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = GitCorpusCache()
    repo = CorpusRepoTarget(
        full_name="acme/api",
        clone_url=(tmp_path / "source").as_uri(),
        default_branch="main",
    )
    root = tmp_path / "corpus"
    bare = root / "local" / "source-deadbeef.git"
    bare.mkdir(parents=True)
    (bare / "HEAD").write_text("ref: refs/heads/main\n")
    monkeypatch.setattr(
        "untaped_github.infrastructure.git_corpus.cache_path_for",
        lambda _url, *, cache_dir: bare,
    )

    def fake_run(
        _args: list[str],
        *,
        cwd: Path | None = None,
        capture_text: bool = False,
        capture_bytes: bool = False,
        check: bool = True,
        timeout: float | None = None,
        auth_header: str | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(_args, 0, stdout=b"Binary file main:asset.bin matches\n")

    monkeypatch.setattr(cache, "_run", fake_run)

    with pytest.raises(GitCorpusError, match="could not parse git grep output"):
        cache.grep_default_branch(
            repo,
            root=root,
            pattern="acme/action",
            paths=(),
            globs=(),
            ignore_case=False,
            fixed_strings=False,
            word_regexp=False,
        )


def test_list_clean_and_worktree_are_confined_to_managed_root(tmp_path: Path) -> None:
    source = _source_repo(tmp_path, "source", {"README.md": "uses: acme/action@v1\n"})
    cache = GitCorpusCache()
    root = tmp_path / "corpus"
    repo = _item("acme/api", source)
    cache.sync_default_branch(repo, root=root, depth=1, auth_header=None)

    [listed] = cache.list_repos(root=root)
    worktree = cache.materialize_worktree(repo, root=root, ref=None)

    assert listed.repo == "acme/api"
    assert listed.path.startswith(str(root))
    assert (Path(worktree.path) / "README.md").is_file()

    [cleaned] = cache.clean_repos(root=root, repos=("acme/api",))

    assert cleaned.status == "removed"
    assert not Path(worktree.path).exists()
    assert cache.list_repos(root=root) == ()


def test_clean_removes_worktree_then_resync_can_materialize_again(tmp_path: Path) -> None:
    source = _source_repo(tmp_path, "source", {"README.md": "uses: acme/action@v1\n"})
    cache = GitCorpusCache()
    root = tmp_path / "corpus"
    repo = _item("acme/api", source)
    cache.sync_default_branch(repo, root=root, depth=1, auth_header=None)
    first = cache.materialize_worktree(repo, root=root, ref=None)

    cache.clean_repos(root=root, repos=("acme/api",))
    cache.sync_default_branch(repo, root=root, depth=1, auth_header=None)
    second = cache.materialize_worktree(repo, root=root, ref=None)

    assert first.path == second.path
    assert (Path(second.path) / "README.md").is_file()


def test_worktree_rejects_non_cached_ref(tmp_path: Path) -> None:
    source = _source_repo(tmp_path, "source", {"README.md": "uses: acme/action@v1\n"})
    cache = GitCorpusCache()
    root = tmp_path / "corpus"
    repo = _item("acme/api", source)
    cache.sync_default_branch(repo, root=root, depth=1, auth_header=None)

    with pytest.raises(GitCorpusError, match="ref is not cached"):
        cache.materialize_worktree(repo, root=root, ref="v1.0")


def test_get_repo_errors_on_corrupt_metadata(tmp_path: Path) -> None:
    cache = GitCorpusCache()
    root = tmp_path / "corpus"
    metadata = root / "github.com" / "api-deadbeef.git" / "untaped-corpus.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("{")

    with pytest.raises(GitCorpusError, match="could not read corpus metadata"):
        cache.get_repo(root=root, repo="acme/api")


def test_list_skips_corrupt_metadata_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source_repo(tmp_path, "source", {"README.md": "uses: acme/action@v1\n"})
    cache = GitCorpusCache()
    root = tmp_path / "corpus"
    cache.sync_default_branch(_item("acme/api", source), root=root, depth=1, auth_header=None)
    corrupt = root / "github.com" / "broken.git" / "untaped-corpus.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{")

    rows = cache.list_repos(root=root)

    assert [row.repo for row in rows] == ["acme/api"]
    assert "warning: could not read corpus metadata" in capsys.readouterr().err


def test_auth_config_is_scoped_to_https_origin() -> None:
    env, path = _auth_config_env(
        "AUTHORIZATION: basic secret",
        auth_url="https://github.example.com/acme/api.git",
    )
    try:
        assert env["GIT_CONFIG_VALUE_0"] == str(path)
        assert path.read_text() == (
            '[http "https://github.example.com/"]\n\textraheader = AUTHORIZATION: basic secret\n'
        )
    finally:
        path.unlink(missing_ok=True)


def test_authenticated_run_failure_captures_and_redacts_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured.update(kwargs)
        assert kwargs["stderr"] is subprocess.PIPE
        assert "capture_output" not in kwargs
        return subprocess.CompletedProcess(
            args,
            1,
            stderr=b"fatal: AUTHORIZATION: basic secret rejected\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache = GitCorpusCache()

    with pytest.raises(GitCorpusError) as excinfo:
        cache._run(
            ["fetch", "origin"],
            auth_header="AUTHORIZATION: basic secret",
            auth_url="https://github.example.com/acme/api.git",
        )

    assert "AUTHORIZATION: basic secret" not in str(excinfo.value)
    assert "fatal: <redacted> rejected" in str(excinfo.value)
    assert captured["stdout"] is None


def test_authenticated_run_scrubs_trace_env_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    child_env: dict[str, str] = {}

    monkeypatch.setenv("GIT_TRACE", "1")
    monkeypatch.setenv("GIT_TRACE_CURL", "1")
    monkeypatch.setenv("GIT_TRACE_CURL_NO_DATA", "1")
    monkeypatch.setenv("GIT_TRACE_PERFORMANCE", "1")
    monkeypatch.setenv("GIT_TRACE2_EVENT", "/tmp/git-trace.json")
    monkeypatch.setenv("GIT_CURL_VERBOSE", "1")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["stderr"] is subprocess.PIPE
        assert kwargs["stdout"] is None
        child_env.update(kwargs["env"])  # type: ignore[arg-type]
        return subprocess.CompletedProcess(args, 0, stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache = GitCorpusCache()

    result = cache._run(
        ["fetch", "origin"],
        auth_header="AUTHORIZATION: basic secret",
        auth_url="https://github.example.com/acme/api.git",
    )

    assert result.returncode == 0
    assert not any(key.startswith("GIT_TRACE") for key in child_env)
    assert "GIT_CURL_VERBOSE" not in child_env
    assert capsys.readouterr().err == ""


def test_unauthenticated_run_keeps_existing_output_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache = GitCorpusCache()

    result = cache._run(["status"])

    assert result.returncode == 0
    assert captured["env"] is None
    assert captured["stdout"] is None
    assert captured["stderr"] is None


def test_auth_config_rejects_non_https_remote() -> None:
    with pytest.raises(GitCorpusError, match="HTTPS clone_url"):
        _auth_config_env("AUTHORIZATION: basic secret", auth_url="git@github.com:acme/api.git")


def test_redact_removes_auth_header() -> None:
    assert (
        _redact(
            "fatal: AUTHORIZATION: basic secret rejected",
            "AUTHORIZATION: basic secret",
        )
        == "fatal: <redacted> rejected"
    )
