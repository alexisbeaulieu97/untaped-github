"""untaped-github: inspect and query GitHub from untaped plugins."""

from untaped_github.domain.models import BatchRepoRefsResult, RepoRef, RepoRefs
from untaped_github.infrastructure import GithubClient
from untaped_github.settings import GithubSettings

__all__ = [
    "BatchRepoRefsResult",
    "GithubClient",
    "GithubSettings",
    "RepoRef",
    "RepoRefs",
]
