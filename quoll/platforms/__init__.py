"""Code hosting platforms: where the repository lives and the CI/CD pipelines run.

Each platform is a sub-package exposing `platform`, a `quoll.platforms.base.Platform`. The project's platform is
`platform` in the [project] section of quoll.toml, detected from the git remote.
"""
from __future__ import annotations

import importlib
import re
import subprocess
from pathlib import Path
from typing import Optional

from quoll.platforms.base import Platform, PlatformError, Remote

__all__ = ["NAMES", "Platform", "PlatformError", "Remote", "detect", "get", "hosting", "parse_remote", "remote"]

NAMES = ("github", "gitlab")


def get(name: str) -> Platform:
    if name not in NAMES:
        raise KeyError(f"unknown platform '{name}' (expected one of: {', '.join(NAMES)})")
    return importlib.import_module(f"quoll.platforms.{name}").platform


def parse_remote(url: str) -> Optional[Remote]:
    """Host and repository path of a git remote URL (https, ssh or scp-like)."""
    m = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)(?::\d+)?[:/](.+?)(?:\.git)?/?$", url.strip())
    if not m or "/" not in m.group(2):
        return None
    return Remote(host=m.group(1).lower(), path=m.group(2))


def remote(project_dir: Path) -> Optional[Remote]:
    """Where `origin` points to."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=project_dir, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_remote(result.stdout) if result.returncode == 0 else None


def hosting(origin: Remote) -> Optional[str]:
    """The platform serving `origin`, when its host tells (github.com, gitlab.com, gitlab.<company>...)."""
    if origin.host == "github.com":
        return "github"
    if "gitlab" in origin.host:
        return "gitlab"
    return None


def detect(project_dir: Path, origin: Optional[Remote] = None) -> str:
    """The platform hosting the project: from the remote's host, else from the pipelines already there."""
    hosted = hosting(origin) if origin else None
    if hosted:
        return hosted
    if (project_dir / ".gitlab-ci.yml").exists() and not (project_dir / ".github" / "workflows").is_dir():
        return "gitlab"
    return "github"
