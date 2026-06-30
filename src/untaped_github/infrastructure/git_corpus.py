"""Local bare Git corpus adapter for scan commands."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from untaped_github.domain import CodeHitResult, CorpusRepoResult, CorpusRepoTarget, WorktreeResult
from untaped_github.domain.errors import GitCorpusError

DEFAULT_TIMEOUT = 60.0
DEFAULT_SLOW_TIMEOUT = 600.0
METADATA_FILE = "untaped-corpus.json"


class GitCorpusCache:
    """Maintain a managed bare Git corpus and search it with ``git grep``."""

    def __init__(
        self,
        *,
        git: str = "git",
        timeout: float = DEFAULT_TIMEOUT,
        slow_timeout: float = DEFAULT_SLOW_TIMEOUT,
    ) -> None:
        self._git = git
        self._git_path = shutil.which(git)
        self._timeout = timeout
        self._slow_timeout = slow_timeout

    def sync_default_branch(
        self,
        repo: CorpusRepoTarget,
        *,
        root: Path,
        depth: int,
        auth_header: str | None,
    ) -> CorpusRepoResult:
        """Fetch a repository's default branch into the managed bare corpus."""
        branch = _default_branch(repo)
        url = _remote_url(repo)
        bare = cache_path_for(url, cache_dir=root)
        if not (bare / "HEAD").is_file():
            bare.parent.mkdir(parents=True, exist_ok=True)
            self._run(["init", "--bare", str(bare)], timeout=self._slow_timeout)
        self._ensure_origin(bare, url, auth_header=auth_header)
        args = ["fetch", "--prune", "origin"]
        if depth > 0:
            args.append(f"--depth={depth}")
        args.append(f"+refs/heads/{branch}:refs/heads/{branch}")
        self._run(args, cwd=bare, timeout=self._slow_timeout, auth_header=auth_header)
        fetched_at = datetime.now(UTC).isoformat()
        _write_metadata(
            bare,
            {
                "repo": repo.full_name,
                "ref": branch,
                "clone_url": url,
                "fetched_at": fetched_at,
            },
        )
        return CorpusRepoResult(
            repo=repo.full_name,
            ref=branch,
            path=str(bare),
            clone_url=url,
            status="synced",
            fetched_at=fetched_at,
        )

    def has_default_branch(self, repo: CorpusRepoTarget, *, root: Path) -> bool:
        branch = _default_branch(repo)
        bare = cache_path_for(_remote_url(repo), cache_dir=root)
        if not (bare / "HEAD").is_file():
            return False
        result = self._run(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=bare,
            check=False,
        )
        return result.returncode == 0

    def grep_default_branch(
        self,
        repo: CorpusRepoTarget,
        *,
        root: Path,
        pattern: str,
        paths: tuple[str, ...],
        globs: tuple[str, ...],
        ignore_case: bool,
        fixed_strings: bool,
        word_regexp: bool,
    ) -> tuple[CodeHitResult, ...]:
        """Run ``git grep`` against one cached default branch."""
        branch = _default_branch(repo)
        bare = cache_path_for(_remote_url(repo), cache_dir=root)
        args = ["grep", "-n", "--column", "-z"]
        if ignore_case:
            args.append("--ignore-case")
        if fixed_strings:
            args.append("--fixed-strings")
        if word_regexp:
            args.append("--word-regexp")
        args.extend(["-e", pattern, branch, "--"])
        args.extend(paths)
        args.extend(f":(glob){glob}" for glob in globs)
        result = cast(
            subprocess.CompletedProcess[bytes],
            self._run(args, cwd=bare, capture_bytes=True, check=False),
        )
        if result.returncode == 1:
            return ()
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode(errors="replace").strip()
            raise GitCorpusError(stderr or f"git grep failed with status {result.returncode}")
        return _parse_grep_output(
            result.stdout or b"",
            repo=repo.full_name,
            ref=branch,
        )

    def list_repos(self, *, root: Path) -> tuple[CorpusRepoResult, ...]:
        """List repositories with corpus metadata under ``root``."""
        managed_root = root.expanduser()
        if not managed_root.exists():
            return ()
        rows: list[CorpusRepoResult] = []
        for metadata_path in sorted(managed_root.rglob(METADATA_FILE)):
            bare = metadata_path.parent
            data = _read_metadata(metadata_path)
            rows.append(
                CorpusRepoResult(
                    repo=str(data.get("repo") or ""),
                    ref=str(data.get("ref") or ""),
                    path=str(bare),
                    clone_url=_optional_str(data.get("clone_url")),
                    status="cached",
                    fetched_at=_optional_str(data.get("fetched_at")),
                )
            )
        return tuple(row for row in rows if row.repo and row.ref)

    def clean_repos(self, *, root: Path, repos: tuple[str, ...]) -> tuple[CorpusRepoResult, ...]:
        """Remove selected repositories from the managed corpus root."""
        managed_root = root.expanduser().resolve()
        rows = self.list_repos(root=root)
        selected = set(repos)
        removed: list[CorpusRepoResult] = []
        for row in rows:
            if selected and row.repo not in selected:
                continue
            bare = Path(row.path).expanduser().resolve()
            if not bare.is_relative_to(managed_root):
                raise GitCorpusError(f"refusing to remove path outside managed root: {bare}")
            shutil.rmtree(bare)
            removed.append(row.model_copy(update={"status": "removed"}))
        return tuple(removed)

    def materialize_worktree(
        self,
        repo: CorpusRepoTarget,
        *,
        root: Path,
        ref: str | None,
    ) -> WorktreeResult:
        """Materialize one cached repository ref into a managed worktree."""
        branch = _default_branch(repo)
        selected_ref = ref or branch
        bare = cache_path_for(_remote_url(repo), cache_dir=root)
        if not (bare / "HEAD").is_file():
            raise GitCorpusError("repository is not in the local corpus")
        worktree = _worktree_path(repo.full_name, selected_ref, root=root)
        if worktree.exists() and not (worktree / ".git").exists():
            raise GitCorpusError(f"worktree path exists and is not a git worktree: {worktree}")
        if worktree.exists():
            self._run(
                ["checkout", "--detach", selected_ref],
                cwd=worktree,
                timeout=self._slow_timeout,
            )
        else:
            worktree.parent.mkdir(parents=True, exist_ok=True)
            self._run(
                ["worktree", "add", "--detach", str(worktree), selected_ref],
                cwd=bare,
                timeout=self._slow_timeout,
            )
        return WorktreeResult(repo=repo.full_name, ref=selected_ref, path=str(worktree))

    def _ensure_origin(self, bare: Path, url: str, *, auth_header: str | None) -> None:
        current = self._run(
            ["remote", "get-url", "origin"],
            cwd=bare,
            capture_text=True,
            check=False,
            auth_header=auth_header,
        )
        current_url = (current.stdout or "").strip()
        if not current_url:
            self._run(["remote", "add", "origin", url], cwd=bare, auth_header=auth_header)
        elif current_url != url:
            self._run(["remote", "set-url", "origin", url], cwd=bare, auth_header=auth_header)

    def _run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        capture_text: bool = False,
        capture_bytes: bool = False,
        check: bool = True,
        timeout: float | None = None,
        auth_header: str | None = None,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        if self._git_path is None:
            raise GitCorpusError(f"`{self._git}` not found on PATH")
        effective_timeout = self._timeout if timeout is None else timeout
        env = None
        auth_config_path: Path | None = None
        if auth_header is not None:
            env, auth_config_path = _auth_config_env(auth_header)
        try:
            result = subprocess.run(
                [self._git_path, *args],
                cwd=cwd,
                env=env,
                text=capture_text,
                capture_output=capture_text or capture_bytes,
                check=False,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitCorpusError(
                f"git {' '.join(args)} timed out after {effective_timeout:g}s"
            ) from exc
        finally:
            if auth_config_path is not None:
                auth_config_path.unlink(missing_ok=True)
        if check and result.returncode != 0:
            stderr = _stderr_text(result)
            raise GitCorpusError(
                f"git {' '.join(args)} failed: {_redact(stderr, auth_header) or 'no stderr'}"
            )
        return result


def cache_path_for(url: str, *, cache_dir: Path) -> Path:
    """Return the deterministic bare-cache path for a remote URL."""
    parsed = urlparse(url)
    if parsed.scheme and parsed.path:
        base_name = Path(parsed.path.rstrip("/")).name
        host = parsed.netloc or "local"
    elif ":" in url and "@" in url.split(":", maxsplit=1)[0]:
        host_part, _, path_part = url.partition(":")
        host = host_part.rsplit("@", maxsplit=1)[-1]
        base_name = Path(path_part.rstrip("/")).name
    else:
        host = "local"
        base_name = Path(url.rstrip("/")).name
    if not base_name:
        base_name = "repository"
    if not base_name.endswith(".git"):
        base_name = f"{base_name}.git"
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    safe_name = _safe_path_part(base_name[:-4])
    return cache_dir.expanduser() / _safe_path_part(host) / f"{safe_name}-{digest}.git"


def git_auth_header(token: str) -> str:
    """Return the transient Git HTTP auth header for a GitHub token."""
    credential = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"AUTHORIZATION: basic {credential}"


def _default_branch(repo: CorpusRepoTarget) -> str:
    if not repo.default_branch:
        raise GitCorpusError(f"repository metadata missing default_branch: {repo.full_name}")
    return repo.default_branch


def _remote_url(repo: CorpusRepoTarget) -> str:
    if repo.clone_url:
        return repo.clone_url
    if repo.html_url:
        return f"{repo.html_url.removesuffix('/')}.git"
    return f"https://github.com/{repo.full_name}.git"


def _parse_grep_output(payload: bytes, *, repo: str, ref: str) -> tuple[CodeHitResult, ...]:
    if not payload:
        return ()
    parts = payload.split(b"\0")
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    rows: list[CodeHitResult] = []
    prefix = f"{ref}:"
    for index in range(0, len(parts), 4):
        try:
            raw_ref_path, raw_line, raw_column, raw_text = parts[index : index + 4]
        except ValueError as exc:
            raise GitCorpusError("could not parse git grep output") from exc
        ref_path = raw_ref_path.decode(errors="replace")
        path = ref_path.removeprefix(prefix)
        rows.append(
            CodeHitResult(
                repo=repo,
                ref=ref,
                path=path,
                line=int(raw_line.decode()),
                column=int(raw_column.decode()),
                text=raw_text.decode(errors="replace").rstrip("\n"),
            )
        )
    return tuple(rows)


def _worktree_path(repo: str, ref: str, *, root: Path) -> Path:
    digest = hashlib.sha256(f"{repo}@{ref}".encode()).hexdigest()[:12]
    name = f"{_safe_path_part(repo)}-{_safe_path_part(ref)}-{digest}"
    return root.expanduser() / "worktrees" / name


def _safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _write_metadata(path: Path, data: dict[str, str]) -> None:
    (path / METADATA_FILE).write_text(json.dumps(data, sort_keys=True) + "\n")


def _read_metadata(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text())
    except OSError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _auth_config_env(auth_header: str) -> tuple[dict[str, str], Path]:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="untaped-git-auth-",
        suffix=".config",
        delete=False,
    ) as auth_config:
        auth_config.write("[http]\n")
        auth_config.write(f"\textraheader = {auth_header}\n")
        path = Path(auth_config.name)
    env = os.environ.copy()
    count = _git_config_count(env)
    env[f"GIT_CONFIG_KEY_{count}"] = "include.path"
    env[f"GIT_CONFIG_VALUE_{count}"] = str(path)
    env["GIT_CONFIG_COUNT"] = str(count + 1)
    return env, path


def _git_config_count(env: dict[str, str]) -> int:
    raw = env.get("GIT_CONFIG_COUNT")
    if raw is None:
        return 0
    try:
        count = int(raw)
    except ValueError:
        return 0
    return max(count, 0)


def _stderr_text(
    result: subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes],
) -> str:
    stderr = result.stderr
    if isinstance(stderr, bytes):
        return stderr.decode(errors="replace").strip()
    return (stderr or "").strip()


def _redact(value: str, secret: str | None) -> str:
    if secret is None:
        return value
    return value.replace(secret, "<redacted>")
