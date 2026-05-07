"""The contract every code hosting platform implements.

A platform knows where its pipelines live and how to render them from quoll.toml (CI from [ci], delivery from
[cd]), and talks to its API to create repositories, store CI secrets and protect branches.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple, Union

if TYPE_CHECKING:
    from quoll.cd.config import CDConfig
    from quoll.ci.config import CIConfig
    from quoll.files import PlannedFile
    from quoll.workspace import Delivery, Repo


class PlatformError(Exception):
    pass


@dataclass(frozen=True)
class Remote:
    """Where a repository is hosted, e.g. ("github.com", "acme/api") or ("gitlab.com", "acme/backend/api")."""

    host: str
    # owner/repo on GitHub; group/[subgroups/]project on GitLab.
    path: str

    @property
    def namespace(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Repo:
    path: str
    clone_url: str
    web_url: str


class PlatformAPI(ABC):
    @abstractmethod
    def create_repo(self, name: str, private: bool = True) -> Repo:
        """Create an empty repository in the configured organization/group, or the user's namespace."""

    @abstractmethod
    def set_secrets(self, repo: str, secrets: Dict[str, str]) -> None:
        """Store CI secrets (GitHub) / masked CI/CD variables (GitLab) on the repository at path `repo`."""

    def ensure_schedule(self, repo: str, branch: str, cron: str) -> bool:
        """Create or update the schedule running the security scans. False when the pipeline file already holds
        it (GitHub's `on: schedule`)."""
        return False

    @abstractmethod
    def protect_branch(
        self, repo: str, branch: str, required_checks: Sequence[str] = (), required_reviews: int = 1
    ) -> List[str]:
        """Forbid direct pushes and require a green pipeline (and reviews) to merge. Returns warnings."""


class Platform(ABC):
    name: str
    label: str
    # What the platform calls the values `quoll` stores for the CI, e.g. "secrets".
    secrets_label: str
    # Registries `quoll cd` can push to; the first is the default.
    registries: Tuple[str, ...]
    # Status checks branch protection requires, when the platform can't require "the pipeline" as a whole.
    required_checks: Tuple[str, ...] = ()
    # Scheduled pipelines are configured through the API rather than in the pipeline file.
    schedules_via_api: bool = False

    @abstractmethod
    def ci_files(self, project_dir: Path, cfg: Union[CIConfig, Repo]) -> List[PlannedFile]:
        """The CI pipeline of a project or a workspace (`Repo`), then files only created when missing."""

    @abstractmethod
    def cd_files(self, project_dir: Path, cfg: Union[CDConfig, List[Delivery]]) -> List[PlannedFile]:
        """The delivery pipeline of a project, or of the workspace members' deliveries."""

    @abstractmethod
    def default_image(self, remote: Optional[Remote], registry: str, fallback_name: str, member: str = "") -> str:
        """Image name `quoll cd` suggests for `registry` (for the workspace `member`, if any)."""

    @abstractmethod
    def registry_secrets(self, registry: str) -> List[str]:
        """Secrets the user must set for `registry` (none for the platform's own registry)."""

    @abstractmethod
    def merge_gate(self) -> str:
        """How to require the pipeline before merging, shown after `quoll ci init`."""

    @abstractmethod
    def api(self, host: Optional[str] = None) -> PlatformAPI:
        """Client for the platform's API (on `host` for self-managed instances)."""
