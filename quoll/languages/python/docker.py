from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from quoll.languages.base import Detection, DockerDefaults, DockerImage
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig

UV_IMAGE = "ghcr.io/astral-sh/uv:0.13"

_LOCKFILES = {"uv": "uv.lock", "poetry": "poetry.lock"}
# Where an application module may live, shallowest first.
_MODULE_GLOBS = ("*.py", "*/*.py", "src/*/*.py", "*/*/*.py", "src/*/*/*.py")
_NOT_APP_DIRS = {"tests", "test", ".venv", "venv", "node_modules", "migrations", "docs"}


class PythonImage(DockerImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        command = _default_command(project)
        warnings = [] if command else ["Couldn't infer how to start the app — set docker.command in quoll.toml."]
        return DockerDefaults(port=8000, command=command, warnings=warnings)

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        lockfile = _LOCKFILES.get(cfg.package_manager, "")
        return {
            "uv_image": UV_IMAGE,
            "lockfile": bool(lockfile) and project.exists(lockfile),
            "requirements": project.exists("requirements.txt"),
            "installable": "build-system" in project.read_toml("pyproject.toml") or project.exists("setup.py"),
            "src_layout": project.is_dir("src"),
        }

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        return [
            ".venv",
            "**/__pycache__",
            "**/*.py[co]",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".coverage",
            "htmlcov",
            "dist",
            "*.egg-info",
            ".env",
            ".env.*",
            "!.env.example",
        ]


def find_app(project: Project, pattern: str) -> Optional[Tuple[str, str]]:
    """(module, name) of the first `<name> = <pattern>` assignment, e.g. ("app.main", "app") for FastAPI()."""
    regex = re.compile(rf"^(\w+)\s*(?::\s*\w+\s*)?=\s*{pattern}", re.M)
    for path in project.glob(*_MODULE_GLOBS):
        rel = path.relative_to(project.root)
        if _NOT_APP_DIRS & set(rel.parts):
            continue
        m = regex.search(path.read_text(errors="ignore"))
        if m:
            parts = list(rel.with_suffix("").parts)
            if parts[0] == "src":  # importable through PYTHONPATH=/app/src
                parts = parts[1:]
            return ".".join(parts), m.group(1)
    return None


def _default_command(project: Project) -> str:
    scripts = project.read_toml("pyproject.toml").get("project", {}).get("scripts", {})
    if scripts:
        return next(iter(scripts))
    for main in project.glob("*/__main__.py", "src/*/__main__.py"):
        if main.parent.name not in _NOT_APP_DIRS:
            return f"python -m {main.parent.name}"
    for name in ("main.py", "app.py", "src/main.py", "src/app.py"):
        if project.exists(name):
            return f"python {name}"
    return ""
