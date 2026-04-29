from __future__ import annotations

import re
from typing import List, Tuple

from quoll.languages.base import Detection
from quoll.project import Project
from quoll.services import detect_services

# Used when the project doesn't say which version it targets.
PYTHON_LATEST = "3.14"
PYTHON_OLDEST = "3.9"

_REQUIREMENT_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "dev-requirements.txt",
    "requirements/dev.txt",
    "requirements/test.txt",
)
# Client libraries revealing a backing service.
_SERVICE_PACKAGES = {
    "postgres": ("psycopg", "psycopg2", "psycopg2-binary", "psycopg-binary", "asyncpg"),
    "mysql": ("mysqlclient", "pymysql", "aiomysql", "mysql-connector-python"),
    "redis": ("redis", "django-redis", "hiredis"),
    "mongodb": ("pymongo", "motor", "mongoengine", "beanie"),
}
# Top-level packages that are never the code under test.
_NOT_SOURCE = ("tests", "test", "docs", "scripts")


def detect(project: Project) -> Detection:
    det = Detection()
    pyproject = project.read_toml("pyproject.toml")
    tool = pyproject.get("tool", {})
    poetry = tool.get("poetry", {})
    meta = pyproject.get("project", {})

    _package_manager(project, tool, det)
    det.install = _install_command(project, pyproject, det)

    requires = meta.get("requires-python") or poetry.get("dependencies", {}).get("python", "")
    low, high = _python_bounds(requires if isinstance(requires, str) else "")
    det.matrix_versions = [f"3.{m}" for m in range(low, high + 1)]
    if project.exists(".python-version"):
        det.version_file = ".python-version"
        pinned = project.read_text(".python-version").split()
        det.version = _major_minor(pinned[0]) if pinned else det.matrix_versions[-1]
    else:
        det.version = det.matrix_versions[-1]

    det.source_dir = _source_dir(project, meta.get("name") or poetry.get("name", ""))
    det.lint_tools = _lint_tools(project, tool)

    has_tests = (
        project.is_dir("tests")
        or project.is_dir("test")
        or project.exists("conftest.py")
        or "pytest" in tool
        or has_dependency(project, "pytest")
    )
    if has_tests:
        det.test_runner = "pytest"
    else:
        det.warnings.append("No tests found (tests/ directory or pytest dependency) — the test job is disabled.")

    packages = [p for names in _SERVICE_PACKAGES.values() for p in names if has_dependency(project, p)]
    det.services = detect_services(packages, _SERVICE_PACKAGES)

    if "build-system" in pyproject:
        det.build_command = {
            "uv": "uv build",
            "poetry": "poetry build",
            "pip": "pip install build\npython -m build",
        }[det.package_manager]
    return det


def _package_manager(project: Project, tool: dict, det: Detection) -> None:
    if project.exists("uv.lock") or "uv" in tool:
        det.package_manager = "uv"
        det.lockfile = "uv.lock" if project.exists("uv.lock") else ""
    elif project.exists("poetry.lock") or "poetry" in tool:
        det.package_manager = "poetry"
        det.lockfile = "poetry.lock" if project.exists("poetry.lock") else ""
    else:
        det.package_manager = "pip"


def _install_command(project: Project, pyproject: dict, det: Detection) -> str:
    if det.package_manager == "uv":
        if det.lockfile:
            return "uv sync --locked --all-extras"
        det.warnings.append("No uv.lock found — run `uv lock` and commit it for reproducible builds.")
        return "uv sync --all-extras"
    if det.package_manager == "poetry":
        if not det.lockfile:
            det.warnings.append("No poetry.lock found — run `poetry lock` and commit it for reproducible builds.")
        return "poetry install --no-interaction --all-extras"

    if not project.exists("requirements.txt", "pyproject.toml", "setup.py"):
        det.warnings.append("No requirements.txt or installable pyproject.toml found — check `install` in quoll.toml.")
    lines = ["python -m pip install --upgrade pip"]
    req_files = [f for f in _REQUIREMENT_FILES if project.exists(f)]
    if req_files:
        lines.append("pip install " + " ".join(f"-r {f}" for f in req_files))
    if "build-system" in pyproject or project.exists("setup.py"):
        optional = pyproject.get("project", {}).get("optional-dependencies", {})
        extras = [e for e in ("dev", "test", "tests") if e in optional]
        target = f'".[{",".join(extras)}]"' if extras else "."
        lines.append(f"pip install -e {target}")
    groups = [g for g in ("dev", "test") if g in pyproject.get("dependency-groups", {})]
    if groups:
        lines.append("pip install " + " ".join(f"--group {g}" for g in groups))
    return "\n".join(lines)


def _lint_tools(project: Project, tool: dict) -> List[str]:
    precommit = project.read_text(".pre-commit-config.yaml")
    setup_cfg = project.read_text("setup.cfg")
    tox_ini = project.read_text("tox.ini")
    tools: List[str] = []
    if "ruff" in tool or project.exists("ruff.toml", ".ruff.toml") or has_dependency(project, "ruff"):
        tools.append("ruff")
        if "format" in tool.get("ruff", {}) or "ruff-format" in precommit:
            tools.append("ruff-format")
    if project.exists(".flake8") or "[flake8]" in setup_cfg or "[flake8]" in tox_ini:
        tools.append("flake8")
    if "black" in tool or re.search(r"\bblack\b", precommit):
        tools.append("black")
    if "mypy" in tool or project.exists("mypy.ini", ".mypy.ini") or "[mypy]" in setup_cfg:
        tools.append("mypy")
    return tools or ["ruff"]


def _python_bounds(spec: str) -> Tuple[int, int]:
    oldest = int(PYTHON_OLDEST.split(".")[1])
    latest = int(PYTHON_LATEST.split(".")[1])
    low, high = latest, latest
    m = re.search(r"(?:>=|\^|~=?|==)\s*3\.(\d+)", spec)
    if m:
        low = max(int(m.group(1)), oldest)
    m = re.search(r"<\s*3\.(\d+)", spec)
    if m:
        high = min(int(m.group(1)) - 1, latest)
    m = re.search(r"<=\s*3\.(\d+)", spec)
    if m:
        high = min(int(m.group(1)), latest)
    return min(low, high), high


def _source_dir(project: Project, project_name: str) -> str:
    if project.is_dir("src"):
        return "src"
    for name in (project_name.replace("-", "_").lower(), project.name.replace("-", "_").lower()):
        if name and project.exists(f"{name}/__init__.py"):
            return name
    packages = [p.parent.name for p in project.glob("*/__init__.py") if p.parent.name not in _NOT_SOURCE]
    return packages[0] if len(packages) == 1 else "."


def has_dependency(project: Project, name: str) -> bool:
    """True when `name` (exactly, not `name-extra`) appears in pyproject.toml or a requirements file."""
    return bool(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", deps_text(project)))


def deps_text(project: Project) -> str:
    files = [project.read_text("pyproject.toml")]
    files += [p.read_text() for p in project.glob("requirements*.txt", "requirements/*.txt")]
    return "\n".join(files).lower()


def _major_minor(version: str) -> str:
    return ".".join(version.strip().split(".")[:2])
