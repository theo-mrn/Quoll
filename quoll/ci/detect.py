"""Inspect a project and infer everything the CI needs, so the user only answers real questions.

Toolchain detection is delegated to the language and framework plugins; this module adds what every project shares
(git, .env.example, Dockerfile).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict

from quoll import languages, platforms
from quoll.ci.config import CIConfig
from quoll.config import quoll_toml
from quoll.languages.base import Detection
from quoll.project import Project

__all__ = ["Detection", "configured_platform", "default_config", "detect", "parse_env_file"]


def detect(project_dir: Path) -> Detection:
    project = Project(project_dir)
    found = languages.matching(project)
    if found:
        language = found[0]
        det = language.detect(project)
        det.stack = language.name
        for framework in languages.frameworks(language.name):
            if framework.detect(project, det):
                det.framework = framework.name
                break
        det.other_stacks = [lang.name for lang in found[1:]]
        if det.other_stacks:
            det.warnings.insert(
                0,
                f"Also found {', '.join(det.other_stacks)} files — quoll configures one stack per repository for now.",
            )
    else:
        det = Detection()
    det.warnings.extend(project.warnings)

    det.has_dockerfile = project.exists("Dockerfile")
    try:
        k8s = quoll_toml.read(project_dir).get("k8s")
    except quoll_toml.ConfigError:
        k8s = None
    det.chart = k8s.get("chart", "chart") if k8s is not None else ""
    if project.exists(".env.example"):
        det.env_vars = parse_env_file(project_dir / ".env.example")
    det.default_branch = default_branch(project_dir)
    det.remote = platforms.remote(project_dir)
    det.platform = configured_platform(project_dir) or platforms.detect(project_dir, det.remote)
    return det


def configured_platform(project_dir: Path) -> str:
    """The platform quoll.toml already names: it wins over the detection."""
    try:
        platform = quoll_toml.read(project_dir).get(quoll_toml.PROJECT_SECTION, {}).get("platform", "")
    except quoll_toml.ConfigError:
        return ""
    return platform if platform in platforms.NAMES else ""


def default_config(det: Detection) -> CIConfig:
    if det.stack is None:
        raise ValueError("cannot build a CI config without a detected stack")
    # GitLab jobs run in images picked by version: they can't read a version file.
    version_file = det.version_file if det.platform == "github" else ""
    language = languages.get(det.stack)
    artifacts = language.ci.build_artifacts(det) if det.build_command else []
    return CIConfig.model_validate(
        {
            "platform": det.platform,
            "stack": det.stack,
            "framework": det.framework,
            "package_manager": det.package_manager,
            "package_manager_version": det.package_manager_version,
            "services": det.services,
            "versions": [] if version_file else [det.version],
            "version_file": version_file,
            "install": det.install,
            "cache": det.cache,
            "source_dir": det.source_dir,
            "branches": [det.default_branch],
            "lint": {"enabled": bool(det.lint_tools), "tools": det.lint_tools},
            "test": {
                "enabled": bool(det.test_runner),
                "runner": det.test_runner,
                "coverage": det.coverage,
                "sanitizers": det.sanitizers,
            },
            "security": {"audit": det.audit},
            "build": {
                "enabled": bool(det.build_command),
                "command": det.build_command,
                "docker": det.has_dockerfile,
                "chart": det.chart,
                "artifacts": artifacts,
            },
        }
    )


# --------------------------------------------------------------------------- git


def _git(project_dir: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=project_dir, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def default_branch(project_dir: Path) -> str:
    remote_head = _git(project_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if remote_head:
        return remote_head.split("/", 1)[-1]
    return _git(project_dir, "branch", "--show-current") or "main"


# --------------------------------------------------------------------------- helpers


def parse_env_file(path: Path) -> Dict[str, str]:
    """Return {key: value} from a .env-style file. Value is empty when unset."""
    result: Dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            result[key] = value.strip().strip("\"'")
    return result
