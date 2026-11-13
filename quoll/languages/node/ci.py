from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from quoll.ci.steps import ROOT, Cache, Item, Step, step
from quoll.languages.base import SCRIPT_PREFIX, CISteps, TestReports
from quoll.platforms.github.actions import ACTIONS

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig
    from quoll.languages.base import Detection

_EXEC = {"npm": "npx", "pnpm": "pnpm exec", "yarn": "yarn", "yarn-classic": "yarn", "bun": "bunx"}

# Files (and directories) quoll writes in a Node project, kept out of its formatter (as in .prettierignore).
# The Helm chart's templates are YAML with Go templates in it: no YAML formatter can read them.
QUOLL_FILES = ("compose.yaml", ".github/", ".gitlab-ci.yml", ".gitlab/", "chart/")
_NOT_QUOLL_FILES = " ".join(f"'!{p}**'" if p.endswith("/") else f"'!{p}'" for p in QUOLL_FILES)

# tool: (step name, command)
_LINT = {
    "eslint": ("ESLint", "eslint ."),
    # quoll's files (compose.yaml, the pipelines) follow their own format, not the project's Prettier config.
    "prettier": ("Prettier", f"prettier --check . {_NOT_QUOLL_FILES}"),
    "biome": ("Biome", "biome ci ."),
    "tsc": ("Type check", "tsc --noEmit"),
}

_COVERAGE_RUNNERS = ("vitest", "jest", "bun")
_BUILD_OUTPUT = {"nextjs": [], "nuxt": [".output/"], "sveltekit": ["build/"]}
_JEST_JUNIT = "/tmp/quoll-jest-junit"
_JEST_JUNIT_INSTALL = f"npm install --no-save --no-package-lock --prefix {_JEST_JUNIT} jest-junit@16"

LOCKFILES = {
    "npm": "package-lock.json",
    "pnpm": "pnpm-lock.yaml",
    "yarn": "yarn.lock",
    "yarn-classic": "yarn.lock",
    "bun": "bun.lock",
}

# Package manager caches, kept in the project by container jobs: (directory, variable pointing the tool at it).
_CACHE = {
    "npm": (".npm", "npm_config_cache"),
    "pnpm": (".pnpm-store", "npm_config_store_dir"),
    "yarn": (".yarn/cache", "YARN_CACHE_FOLDER"),
    "yarn-classic": (".yarn-cache", "YARN_CACHE_FOLDER"),
}

_AUDIT = {
    "npm": "npm audit --omit=dev --audit-level=high",
    "pnpm": "pnpm audit --prod --audit-level high",
    "yarn": "yarn npm audit --environment production --severity high",
    "yarn-classic": "yarn audit --groups dependencies --level high",
    "bun": "bun audit --prod --audit-level=high",
}


def run_script(package_manager: str, script: str) -> str:
    if package_manager.startswith("yarn"):
        return f"yarn run {script}"
    return f"{package_manager} run {script}"


class NodeCI(CISteps):
    # npm / pnpm / yarn / bun audit read the lockfile, installing nothing.
    audit_uses_cache = False
    version_key = "node-version"
    codeql_language = "javascript-typescript"

    def setup(self, cfg: CIConfig, version: Optional[str]) -> List[Item]:
        pm = cfg.package_manager
        pinned = cfg.package_manager_version
        steps = []
        if pm == "pnpm":
            with_pnpm = {"version": pinned} if pinned else {}
            if cfg.directory != ".":
                with_pnpm["package_json_file"] = cfg.path("package.json")
            steps.append(step("Set up pnpm", uses=ACTIONS["setup-pnpm"], with_=with_pnpm))
        elif pm == "yarn":
            # Yarn Berry is provided by corepack; it must be enabled before setup-node resolves the cache.
            steps.append(step("Enable corepack", run="corepack enable"))
        elif pm == "bun":
            steps.append(
                step("Set up Bun", uses=ACTIONS["setup-bun"], with_={"bun-version": pinned} if pinned else None)
            )

        with_: Dict[str, Any] = (
            {"node-version": version} if version else {"node-version-file": cfg.path(cfg.version_file)}
        )
        if cfg.cache and pm != "bun":
            with_["cache"] = "yarn" if pm.startswith("yarn") else pm
            if cfg.directory != ".":
                with_["cache-dependency-path"] = cfg.path(LOCKFILES[pm])
        steps.append(step("Set up Node.js", uses=ACTIONS["setup-node"], with_=with_))
        return steps

    def image(self, cfg: CIConfig, version: str) -> str:
        if cfg.package_manager == "bun":
            return f"oven/bun:{cfg.package_manager_version or '1'}"
        return f"node:{'lts' if version.startswith('lts') else version}"

    def image_setup(self, cfg: CIConfig) -> List[Step]:
        pm = cfg.package_manager
        if pm not in ("pnpm", "yarn"):
            return []
        # Corepack provides the version pinned in package.json "packageManager"; Node 25+ no longer bundles it.
        pinned = cfg.package_manager_version
        run = "npm install --global corepack@latest\ncorepack enable"
        if pinned:
            run += f"\ncorepack install --global {pm}@{pinned}"
        return [step(f"Set up {pm}", run=run, env={"COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"})]

    def cache(self, cfg: CIConfig) -> Optional[Cache]:
        # Bun's cache holds unpacked sources that linters would scan: it installs fast enough without.
        if not cfg.cache or cfg.package_manager not in _CACHE:
            return None
        directory, variable = _CACHE[cfg.package_manager]
        env = {variable: f"{ROOT}/{directory}"}
        if cfg.package_manager == "yarn":
            env["YARN_ENABLE_GLOBAL_CACHE"] = "false"
        return Cache("node", (directory,), key_files=(LOCKFILES[cfg.package_manager],), env=env)

    def install(self, cfg: CIConfig, packages: Sequence[str] = ()) -> List[Item]:
        return [step("Install dependencies", run=cfg.install)]

    def exec(self, cfg: CIConfig, command: str) -> str:
        return f"{_EXEC[cfg.package_manager]} {command}"

    def lint(self, cfg: CIConfig, tools: List[str]) -> List[Item]:
        steps = self.install(cfg)
        for tool in tools:
            if tool.startswith(SCRIPT_PREFIX):
                script = tool[len(SCRIPT_PREFIX):]
                steps.append(step(f"Run {script}", run=run_script(cfg.package_manager, script)))
            else:
                name, cmd = _LINT[tool]
                steps.append(step(name, run=self.exec(cfg, cmd)))
        return steps

    def test(self, cfg: CIConfig) -> List[Item]:
        t = cfg.test
        coverage = t.coverage
        setup: List[Item] = []
        env: Dict[str, str] = {}
        if t.runner == "jest":
            cmd = self.exec(cfg, "jest --ci")
            if coverage:
                cmd += f""" --coverage --coverageThreshold='{{"global":{{"lines":{t.coverage_threshold}}}}}'"""
                if t.reports:
                    cmd += " --coverageReporters=text --coverageReporters=lcov --coverageReporters=cobertura"
            if t.reports:
                # Jest has no JUnit output of its own: jest-junit, installed outside the project.
                setup.append(step("JUnit reporter for Jest", run=_JEST_JUNIT_INSTALL))
                cmd += f" --reporters=default --reporters={_JEST_JUNIT}/node_modules/jest-junit"
                env = {"JEST_JUNIT_OUTPUT_DIR": ".", "JEST_JUNIT_OUTPUT_NAME": "junit.xml"}
        elif t.runner == "vitest":
            cmd = self.exec(cfg, "vitest run")
            if t.reports:
                cmd += " --reporter=default --reporter=junit --outputFile.junit=junit.xml"
            if coverage:
                cmd += (
                    " --coverage.enabled --coverage.reporter=text --coverage.reporter=lcov"
                    + (" --coverage.reporter=cobertura" if t.reports else "")
                    + f" --coverage.thresholds.lines={t.coverage_threshold}"
                )
        elif t.runner == "bun":
            cmd = "bun test --coverage --coverage-reporter=lcov" if coverage else "bun test"
            if t.reports:
                cmd += " --reporter=junit --reporter-outfile=junit.xml"
        else:
            cmd = run_script(cfg.package_manager, t.runner[len(SCRIPT_PREFIX):])
            coverage = False
        name = "Tests" + (" with coverage" if coverage else "")
        return [*self.install(cfg), *setup, step(name, run=cmd, env=env, secrets=t.env_secrets)]

    def coverage_file(self, cfg: CIConfig) -> str:
        return "coverage/lcov.info"

    def reports(self, cfg: CIConfig) -> TestReports:
        runner, coverage = cfg.test.runner, cfg.test.coverage
        return TestReports(
            junit="junit.xml" if runner in ("vitest", "bun", "jest") else "",
            cobertura="coverage/cobertura-coverage.xml" if coverage and runner in ("vitest", "jest") else "",
            # The "All files" row of the text coverage table.
            coverage_regex=r"/All files\s*\|\s*(\d+(?:\.\d+)?)/" if coverage and runner in _COVERAGE_RUNNERS else "",
        )

    def audit(self, cfg: CIConfig) -> List[Item]:
        return [step("Dependency vulnerability scan", run=_AUDIT[cfg.package_manager])]

    def build(self, cfg: CIConfig) -> List[Item]:
        return [*self.install(cfg), step("Build", run=cfg.build.command)]

    def build_artifacts(self, det: Detection) -> List[str]:
        # Vite, Angular, tsc, NestJS... build into dist/; Next.js' .next/ isn't something to ship as is.
        return _BUILD_OUTPUT.get(det.framework or "", ["dist/"])

    def dependabot_ecosystem(self, cfg: CIConfig) -> str:
        return "bun" if cfg.package_manager == "bun" else "npm"
