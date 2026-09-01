"""Repositories holding several projects (a front-end and a back-end, services...), each with its own quoll.toml.

The root quoll.toml lists them and holds what the repository shares; every member keeps the format of a
single project, so a member taken out of the repository stays a valid quoll project:

    # quoll.toml
    [project]
    platform = "github"

    [workspace]
    members = ["backend", "frontend"]

    [ci]                       # the repository's: when pipelines run, repository-wide scans
    branches = ["main"]

    # backend/quoll.toml, frontend/quoll.toml: [project], [ci], [docker], [cd] as usual

A repository with a single project is the one-member case: everything below works for both.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from pydantic import Field, model_validator

from quoll.cd.config import CDConfig
from quoll.cd.config import load_config as load_cd_config
from quoll.ci.config import CIConfig, ScheduleConfig, load_config
from quoll.config.quoll_toml import CONFIG_FILE, ConfigError, PlatformField, Section, load_section, read, save_section
from quoll.k8s.config import K8sConfig
from quoll.k8s.config import load_config as load_k8s_config

WORKSPACE_SECTION = "workspace"


class WorkspaceConfig(Section):
    # Directories of the projects, relative to the repository root ("." for a project at the root).
    members: List[str]

    @model_validator(mode="after")
    def _check(self) -> "WorkspaceConfig":
        if not self.members:
            raise ValueError("workspace.members must list at least one project directory")
        names = [member_name(m) for m in self.members]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"two members would be named '{duplicates[0]}': rename one of their directories")
        return self


class RepoSecurity(Section):
    # Scans of the whole repository, run once whatever the members.
    secrets: bool = True
    sast: bool = True


class RepoCIConfig(Section, PlatformField):
    """[ci] of a workspace root: what the members share."""

    shared_fields = ("platform",)

    branches: List[str] = Field(default_factory=lambda: ["main"])
    dependency_updates: bool = True
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    security: RepoSecurity = Field(default_factory=RepoSecurity)


@dataclass
class Member:
    # Job prefix: the last part of its directory ("" for a single project).
    name: str
    cfg: CIConfig

    @property
    def directory(self) -> str:
        return self.cfg.directory

    def job(self, job: str) -> str:
        return f"{self.name}-{job}" if self.name else job


@dataclass
class Delivery:
    """The delivery of one project: [cd] of a single project ("" name), or of a workspace member."""

    name: str
    directory: str
    cfg: CDConfig
    # Its Helm chart, deployed to each environment once the image is published.
    k8s: Optional[K8sConfig] = None


@dataclass
class Repo:
    """Everything one pipeline covers: the repository's settings and its projects."""

    platform: str
    branches: List[str]
    dependency_updates: bool
    schedule: ScheduleConfig
    secrets: bool
    sast: bool
    members: List[Member]

    @property
    def workspace(self) -> bool:
        return any(m.name for m in self.members)

    @classmethod
    def single(cls, cfg: CIConfig) -> "Repo":
        return cls(
            platform=cfg.platform,
            branches=list(cfg.branches),
            dependency_updates=cfg.dependency_updates,
            schedule=cfg.schedule,
            secrets=cfg.security.secrets,
            sast=cfg.security.sast,
            members=[Member("", cfg)],
        )


# Directories that hold no project of their own, even with a requirements.txt or a package.json (docs, examples).
_NOT_PROJECTS = {
    "docs", "doc", "examples", "example", "samples", "test", "tests", "fixtures", "scripts", "node_modules",
    "vendor", "dist", "build", "target", "venv", ".venv",
}
# Where monorepos usually keep their projects, one level deeper.
_CONTAINERS = ("apps", "packages", "services")


def discover(root: Path) -> List[str]:
    """Project directories of the repository: the root, its first-level directories and apps/*, packages/*,
    services/* — each where quoll recognizes a language."""
    from quoll import languages
    from quoll.project import Project

    candidates = [root]
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in _NOT_PROJECTS:
            continue
        if child.name in _CONTAINERS:
            candidates += sorted(c for c in child.iterdir() if c.is_dir() and not c.name.startswith("."))
        else:
            candidates.append(child)
    found = []
    for directory in candidates:
        if languages.matching(Project(directory)):
            found.append(directory.relative_to(root).as_posix() or ".")
    return found


def member_name(directory: str) -> str:
    """backend -> backend, apps/web -> web, . -> root."""
    parts = [p for p in directory.strip("/").split("/") if p and p != "."]
    return parts[-1] if parts else "root"


def find_root(start: Path) -> Path:
    """The workspace root `start` belongs to (itself or a parent listing it), else `start`."""
    start = start.resolve()
    for candidate in [start, *start.parents]:
        try:
            data = read(candidate)
        except ConfigError:
            continue
        workspace = data.get(WORKSPACE_SECTION)
        if workspace is None:
            continue
        members = [(candidate / m).resolve() for m in workspace.get("members", [])]
        if candidate == start or start in members:
            return candidate
    return start


def load_workspace(root: Path) -> Optional[WorkspaceConfig]:
    data = read(root)
    if WORKSPACE_SECTION not in data:
        return None
    return load_section(root, WORKSPACE_SECTION, WorkspaceConfig)


def load_repo(root: Path) -> Repo:
    """The repository's pipeline settings: a workspace's, or a single project's (its [ci])."""
    workspace = load_workspace(root)
    if workspace is None:
        return Repo.single(load_config(root))
    shared = load_section(root, "ci", RepoCIConfig)
    members = []
    for directory in workspace.members:
        cfg = load_config(root / directory)
        if cfg.platform != shared.platform:
            raise ConfigError(
                f"{directory}/{CONFIG_FILE} targets {cfg.platform}, the workspace {shared.platform}: "
                "set the same [project] platform"
            )
        members.append(Member(member_name(directory), cfg.in_directory(directory)))
    return Repo(
        platform=shared.platform,
        branches=list(shared.branches),
        dependency_updates=shared.dependency_updates,
        schedule=shared.schedule,
        secrets=shared.security.secrets,
        sast=shared.security.sast,
        members=members,
    )


def save_workspace(root: Path, members: List[str], shared: RepoCIConfig) -> None:
    save_section(root, WORKSPACE_SECTION, WorkspaceConfig(members=members))
    save_section(root, "ci", shared)


def load_deliveries(root: Path) -> List[Delivery]:
    """The [cd] of a single project, or of each workspace member that has one."""
    workspace = load_workspace(root)
    if workspace is None:
        return [Delivery("", ".", load_cd_config(root), _chart(root))]
    deliveries = []
    for directory in workspace.members:
        if "cd" in read(root / directory):
            deliveries.append(
                Delivery(member_name(directory), directory, load_cd_config(root / directory), _chart(root / directory))
            )
    if not deliveries:
        raise ConfigError("no workspace member has a [cd] section. Run `quoll cd init` in one of them first.")
    return deliveries


def _chart(directory: Path) -> Optional[K8sConfig]:
    return load_k8s_config(directory) if "k8s" in read(directory) else None
