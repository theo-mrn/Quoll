from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from quoll.ci.steps import ROOT, Cache, Item, Step, on_github, step
from quoll.languages.base import CISteps, TestReports
from quoll.platforms.github.actions import ACTIONS

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig
    from quoll.languages.base import Detection

# The TOTAL line of `coverage report` / pytest-cov.
COVERAGE_REGEX = r"/TOTAL.*\s(\d+(?:\.\d+)?)%/"

_RUN_PREFIX = {"pip": "", "uv": "uv run --no-sync ", "poetry": "poetry run "}
_TOOL_INSTALL = {"pip": "pip install", "uv": "uv pip install", "poetry": "poetry run pip install"}

# tool: (step name, package to install, command)
_LINT = {
    "ruff": ("Ruff", "ruff", "ruff check{github} ."),
    "ruff-format": ("Ruff format", "ruff", "ruff format --check --diff ."),
    "flake8": ("Flake8", "flake8", "flake8 ."),
    "black": ("Black", "black", "black --check --diff ."),
    "mypy": ("Mypy", "mypy", "mypy {source_dir}"),
}


class PythonCI(CISteps):
    version_key = "python-version"
    codeql_language = "python"

    def setup(self, cfg: CIConfig, version: Optional[str]) -> List[Item]:
        if cfg.package_manager == "uv":
            with_: Dict[str, Any] = {}
            if version:
                with_["python-version"] = version
            if cfg.cache:
                with_["enable-cache"] = True
            if cfg.directory != ".":
                with_["working-directory"] = cfg.directory
            return [step("Set up uv", uses=ACTIONS["setup-uv"], with_=with_ or None)]

        steps = []
        if cfg.package_manager == "poetry":
            steps.append(step("Install Poetry", run="pipx install poetry"))
        with_ = {"python-version": version} if version else {"python-version-file": cfg.path(cfg.version_file)}
        if cfg.cache:
            with_["cache"] = cfg.package_manager
            if cfg.package_manager == "pip":
                with_["cache-dependency-path"] = f"{cfg.path('**/requirements*.txt')}\n{cfg.path('**/pyproject.toml')}"
            elif cfg.directory != ".":
                with_["cache-dependency-path"] = cfg.path("poetry.lock")
        steps.append(step("Set up Python", uses=ACTIONS["setup-python"], with_=with_))
        return steps

    def image(self, cfg: CIConfig, version: str) -> str:
        if cfg.package_manager == "uv":
            return f"ghcr.io/astral-sh/uv:python{version}-bookworm"
        return f"python:{version}"

    def image_setup(self, cfg: CIConfig) -> List[Step]:
        if cfg.package_manager == "poetry":
            return [step("Install Poetry", run="pip install poetry")]
        return []

    def cache(self, cfg: CIConfig) -> Optional[Cache]:
        if not cfg.cache:
            return None
        if cfg.package_manager == "pip":
            return Cache("pip", (".cache/pip",), env={"PIP_CACHE_DIR": f"{ROOT}/.cache/pip"})
        # The virtualenv itself, in the project (linters and pytest skip .venv).
        lockfile = "uv.lock" if cfg.package_manager == "uv" else "poetry.lock"
        env = {"POETRY_VIRTUALENVS_IN_PROJECT": "true"} if cfg.package_manager == "poetry" else {}
        return Cache("venv", (".venv",), key_files=(lockfile,), env=env)

    def install(self, cfg: CIConfig, packages: Sequence[str] = ()) -> List[Item]:
        steps = [step("Install dependencies", run=cfg.install)]
        if packages:
            steps.append(step("Install CI tools", run=f"{_TOOL_INSTALL[cfg.package_manager]} {' '.join(packages)}"))
        return steps

    def exec(self, cfg: CIConfig, command: str) -> str:
        return _RUN_PREFIX[cfg.package_manager] + command

    def lint(self, cfg: CIConfig, tools: List[str]) -> List[Item]:
        specs = [_LINT[t] for t in tools]
        steps = self.install(cfg, sorted({package for _, package, _ in specs}))
        github = on_github(cfg, " --output-format=github")
        for name, _, cmd in specs:
            steps.append(step(name, run=self.exec(cfg, cmd.format(source_dir=cfg.source_dir, github=github))))
        return steps

    def test(self, cfg: CIConfig) -> List[Item]:
        t = cfg.test
        cmd = self.exec(cfg, "pytest")
        if t.coverage:
            cmd += (
                f" --cov={cfg.source_dir} --cov-report=xml --cov-report=term-missing"
                f" --cov-fail-under={t.coverage_threshold}"
            )
        if t.reports:
            cmd += " --junitxml=junit.xml"
        steps = self.install(cfg, ["pytest", "pytest-cov"] if t.coverage else ["pytest"])
        steps.append(step("Tests" + (" with coverage" if t.coverage else ""), run=cmd, secrets=t.env_secrets))
        if t.coverage:
            steps.append(coverage_summary(cfg))
        return steps

    def coverage_file(self, cfg: CIConfig) -> str:
        return "coverage.xml"

    def reports(self, cfg: CIConfig) -> TestReports:
        coverage = cfg.test.coverage
        return TestReports(
            junit="junit.xml" if cfg.test.runner == "pytest" else "",
            cobertura="coverage.xml" if coverage else "",
            coverage_regex=COVERAGE_REGEX if coverage else "",
        )

    def audit(self, cfg: CIConfig) -> List[Item]:
        if cfg.package_manager == "uv":
            # uv venvs have no pip, so audit the locked requirements instead of the environment.
            return [
                step(
                    "Export locked dependencies",
                    run="uv export --format requirements-txt --no-emit-project --output-file requirements-audit.txt",
                ),
                step(
                    "Dependency vulnerability scan",
                    run="uvx pip-audit --requirement requirements-audit.txt --require-hashes --disable-pip",
                ),
            ]
        steps = self.install(cfg, ["pip-audit"])
        steps.append(step("Dependency vulnerability scan", run=self.exec(cfg, "pip-audit --skip-editable")))
        return steps

    def build(self, cfg: CIConfig) -> List[Item]:
        return [step("Build", run=cfg.build.command)]

    def build_artifacts(self, det: Detection) -> List[str]:
        # Wheels and source distributions (uv build, python -m build, poetry build).
        return ["dist/"] if "build" in det.build_command else []

    def dependabot_ecosystem(self, cfg: CIConfig) -> str:
        return "uv" if cfg.package_manager == "uv" else "pip"


def coverage_summary(cfg: CIConfig) -> Step:
    """Coverage table in the job summary page, from the data left by pytest-cov or `coverage run`."""
    return step(
        "Coverage summary",
        run=_RUN_PREFIX[cfg.package_manager] + 'coverage report --format=markdown >> "$GITHUB_STEP_SUMMARY"',
        always=True,
        optional=True,
        summary=True,
    )
