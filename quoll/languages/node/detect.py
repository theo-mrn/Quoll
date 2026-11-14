from __future__ import annotations

import re
from typing import Dict, List

from quoll.languages.base import SCRIPT_PREFIX, Detection
from quoll.languages.node.ci import run_script
from quoll.project import Project
from quoll.services import detect_services

# Used when the project doesn't say which version it targets, and by the starters: the active LTS.
NODE_DEFAULT = "26"
NODE_SUPPORTED = ("22", "24", "26")
PNPM_DEFAULT = "10"

# Checked in order: the first lockfile found decides the package manager.
_LOCKFILES = (
    ("pnpm-lock.yaml", "pnpm"),
    ("bun.lock", "bun"),
    ("bun.lockb", "bun"),
    ("yarn.lock", "yarn"),
    ("package-lock.json", "npm"),
)

# (frozen install, plain install)
_INSTALL = {
    "npm": ("npm ci", "npm install"),
    "pnpm": ("pnpm install --frozen-lockfile", "pnpm install"),
    "yarn": ("yarn install --immutable", "yarn install"),
    "yarn-classic": ("yarn install --frozen-lockfile", "yarn install"),
    "bun": ("bun install --frozen-lockfile", "bun install"),
}

_NPM_PLACEHOLDER_TEST = "no test specified"

# Client libraries revealing a backing service.
_SERVICE_PACKAGES = {
    "postgres": ("pg", "postgres", "pg-promise", "@vercel/postgres"),
    "mysql": ("mysql2", "mysql"),
    "redis": ("redis", "ioredis", "bullmq", "@upstash/redis"),
    "mongodb": ("mongodb", "mongoose"),
}
# Prisma's datasource provider -> service.
_PRISMA_PROVIDERS = {"postgresql": "pg", "mysql": "mysql2", "mongodb": "mongodb"}


def detect(project: Project) -> Detection:
    det = Detection()
    pkg = package_json(project)
    scripts = scripts_of(pkg)
    deps = dependencies(pkg)

    _package_manager(project, pkg.get("packageManager") or "", det)
    det.install = _INSTALL[det.package_manager][0 if det.lockfile else 1]
    if not det.lockfile:
        det.cache = False
        det.warnings.append(
            "No lockfile found — CI installs will not be reproducible. "
            "Commit your lockfile and run `quoll ci init` again."
        )

    _version(project, pkg, det)
    det.lint_tools = _lint_tools(project, pkg, scripts, deps)
    _test_runner(scripts, deps, det)
    if "build" in scripts:
        det.build_command = run_script(det.package_manager, "build")
    det.services = detect_services([*deps, *_prisma_clients(project)], _SERVICE_PACKAGES)
    return det


def _prisma_clients(project: Project) -> List[str]:
    """The client package matching prisma/schema.prisma's provider, so Prisma projects get their database."""
    m = re.search(r'provider\s*=\s*"(\w+)"', project.read_text("prisma/schema.prisma").split("datasource", 1)[-1])
    return [_PRISMA_PROVIDERS[m.group(1)]] if m and m.group(1) in _PRISMA_PROVIDERS else []


def _package_manager(project: Project, declared: str, det: Detection) -> None:
    for name, pm in _LOCKFILES:
        if project.exists(name):
            det.package_manager, det.lockfile = pm, name
            break
    else:
        pm = declared.split("@")[0]
        det.package_manager = pm if pm in ("pnpm", "yarn", "bun", "npm") else "npm"

    if det.package_manager == "yarn":
        major = re.match(r"yarn@(\d+)", declared)
        classic = major.group(1) == "1" if major else not project.exists(".yarnrc.yml")
        if classic:
            det.package_manager = "yarn-classic"

    if det.package_manager == "pnpm" and not declared.startswith("pnpm@"):
        det.package_manager_version = PNPM_DEFAULT


def _version(project: Project, pkg: dict, det: Detection) -> None:
    for name in (".nvmrc", ".node-version"):
        if project.exists(name):
            det.version_file = name
            raw = project.read_text(name).strip().lstrip("v")
            det.version = raw.split(".")[0] if raw[:1].isdigit() else NODE_DEFAULT
            break
    else:
        m = re.search(r"(\d+)", (pkg.get("engines") or {}).get("node", ""))
        det.version = m.group(1) if m else NODE_DEFAULT
    low = int(det.version) if det.version.isdigit() else 0
    det.matrix_versions = [v for v in NODE_SUPPORTED if int(v) >= low] or [det.version]


def _lint_tools(project: Project, pkg: dict, scripts: Dict[str, str], deps: dict) -> List[str]:
    tools: List[str] = []
    has_biome = "@biomejs/biome" in deps or project.glob_any("biome.json", "biome.jsonc")
    if "lint" in scripts:
        tools.append(f"{SCRIPT_PREFIX}lint")
    elif has_biome:
        tools.append("biome")
    elif "eslint" in deps or project.glob_any("eslint.config.*", ".eslintrc*"):
        tools.append("eslint")

    if "format:check" in scripts:
        tools.append(f"{SCRIPT_PREFIX}format:check")
    elif not has_biome and (
        "prettier" in deps or "prettier" in pkg or project.glob_any(".prettierrc*", "prettier.config.*")
    ):
        tools.append("prettier")

    typecheck = next((s for s in ("typecheck", "type-check", "check-types") if s in scripts), None)
    if typecheck:
        tools.append(f"{SCRIPT_PREFIX}{typecheck}")
    elif project.exists("tsconfig.json") and "typescript" in deps:
        tools.append("tsc")
    return tools


def _test_runner(scripts: Dict[str, str], deps: dict, det: Detection) -> None:
    test_script = scripts.get("test", "")
    if "vitest" in deps:
        det.test_runner = "vitest"
        det.coverage = any(p in deps for p in ("@vitest/coverage-v8", "@vitest/coverage-istanbul"))
        if not det.coverage:
            det.warnings.append("vitest coverage needs @vitest/coverage-v8 — coverage is disabled until you add it.")
    elif "jest" in deps:
        det.test_runner = "jest"
    elif det.package_manager == "bun" and (not test_script or "bun test" in test_script):
        det.test_runner = "bun"
    elif test_script and _NPM_PLACEHOLDER_TEST not in test_script:
        det.test_runner = f"{SCRIPT_PREFIX}test"
        det.coverage = False
    else:
        det.warnings.append("No test runner found (vitest, jest or a `test` script) — the test job is disabled.")


def package_json(project: Project) -> dict:
    pkg = project.read_json("package.json")
    return pkg if isinstance(pkg, dict) else {}


def dependencies(pkg: dict) -> Dict[str, str]:
    """`dependencies` and `devDependencies`, merged."""
    return {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}


def scripts_of(pkg: dict) -> Dict[str, str]:
    return pkg.get("scripts") or {}
