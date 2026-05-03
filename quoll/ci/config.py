"""The [ci] section of quoll.toml — the single source of truth for the generated workflow."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from pydantic import ConfigDict, Field, field_validator, model_validator

from quoll.config.quoll_toml import CONFIG_FILE, ConfigError, ProjectConfig, Section, load_section, save_section

__all__ = ["CONFIG_FILE", "CIConfig", "ConfigError", "load_config", "save_config"]


SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")


class LintConfig(Section):
    enabled: bool = True
    tools: List[str] = Field(default_factory=list)


class TestConfig(Section):
    __test__ = False  # not a pytest test class

    enabled: bool = True
    runner: str = ""
    coverage: bool = True
    coverage_threshold: int = Field(default=80, ge=0, le=100)
    codecov: bool = False
    # Test results (JUnit) and coverage (Cobertura) shown in pull/merge requests, where the runner produces them.
    reports: bool = True
    # Run the tests with AddressSanitizer and UndefinedBehaviorSanitizer (C/C++).
    sanitizers: bool = False
    env_secrets: List[str] = Field(default_factory=list)


class SecurityConfig(Section):
    # Known vulnerabilities in the dependencies.
    audit: bool = True
    # Credentials committed anywhere in the git history (gitleaks).
    secrets: bool = True
    # Static analysis of the code for bugs and vulnerabilities (Semgrep), every language.
    sast: bool = True
    # GitHub CodeQL; results in the Security tab (needs GitHub Advanced Security on private repositories).
    codeql: bool = False
    # Software bill of materials of the dependencies (CycloneDX), kept as a pipeline artifact.
    sbom: bool = True
    # Fail on dependencies whose license falls in these Trivy categories: CRITICAL = forbidden (AGPL, SSPL...),
    # HIGH = restricted (GPL, LGPL), MEDIUM = reciprocal (MPL, EPL), LOW = notice (MIT, Apache, BSD).
    licenses: bool = True
    license_severity: List[str] = Field(default_factory=lambda: ["CRITICAL"])
    sonar: bool = False
    sonar_organization: str = ""
    sonar_project_key: str = ""


class BuildConfig(Section):
    enabled: bool = False
    command: str = ""
    docker: bool = False
    # The project's Helm chart (directory): linted, checked against Kubernetes' schemas, scanned.
    chart: str = ""
    # What the build produces, kept a week (paths or globs in the project, e.g. "dist/", "target/*.jar").
    artifacts: List[str] = []


# Generated jobs custom steps can extend.
EXTENSIBLE_JOBS = ("lint", "test", "build", "audit", "sbom")
# Jobs the scheduled pipeline runs: new vulnerabilities appear without any code change.
SECURITY_JOBS = ("audit", "secrets", "sast", "codeql", "sbom", "docker")


class CustomStep(Section):
    """A step added to one of the generated jobs. For anything bigger, write plain CI next to quoll's: GitHub
    workflows using the quoll-setup action, GitLab jobs in .gitlab/custom-ci.yml."""

    job: str
    # before: once the dependencies are installed, before the job's own commands; after: at the end.
    when: str = "before"
    name: str
    # A shell command...
    run: str = ""
    # ...or a GitHub Action (GitHub only), with its inputs.
    uses: str = ""
    with_: Dict[str, Any] = Field(default_factory=dict, alias="with")
    env: Dict[str, str] = Field(default_factory=dict)
    # CI secrets / variables the step reads.
    secrets: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    @model_validator(mode="after")
    def _check(self) -> "CustomStep":
        if self.job not in EXTENSIBLE_JOBS:
            raise ValueError(f"unknown job '{self.job}' (expected one of: {', '.join(EXTENSIBLE_JOBS)})")
        if self.when not in ("before", "after"):
            raise ValueError(f"when must be 'before' or 'after', not '{self.when}'")
        if bool(self.run) == bool(self.uses):
            raise ValueError(f"step '{self.name}' needs either run or uses")
        if self.with_ and not self.uses:
            raise ValueError(f"step '{self.name}': with only goes with uses")
        return self


class ScheduleConfig(Section):
    # Re-run the security jobs on a schedule (GitHub: in the workflow; GitLab: a pipeline schedule).
    enabled: bool = True
    # Cron expression, UTC. Default: Mondays at 06:00.
    cron: str = "0 6 * * 1"

    @field_validator("cron")
    @classmethod
    def _five_fields(cls, value: str) -> str:
        if len(value.split()) != 5:
            raise ValueError(f"cron '{value}' must have 5 fields (minute hour day month weekday)")
        return value


class CIConfig(ProjectConfig):
    omit_when_empty = ("steps", "build.artifacts", "build.chart")

    # Exact versions to test against. More than one turns the test job into a matrix.
    versions: List[str] = Field(default_factory=list)
    # Used when `versions` is empty: let the setup action read .python-version, .nvmrc, go.mod... (GitHub only:
    # GitLab jobs run in images chosen by version).
    version_file: str = ""
    install: str
    cache: bool = True
    source_dir: str = "."
    branches: List[str] = Field(default_factory=lambda: ["main"])
    # Dependabot on GitHub, Renovate on GitLab. Their config is only created, never overwritten.
    dependency_updates: bool = True
    lint: LintConfig = Field(default_factory=LintConfig)
    test: TestConfig = Field(default_factory=TestConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    build: BuildConfig = Field(default_factory=BuildConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    # Your own steps in the generated jobs ([[ci.steps]]), kept across `quoll ci update`.
    steps: List[CustomStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self) -> "CIConfig":
        lang = self.language
        for tool in self.lint.tools:
            if not self.is_lint_tool(tool):
                raise ValueError(
                    f"unknown lint tool '{tool}' for {self.target} (expected one of: {', '.join(self.lint_tools)})"
                )
        if self.test.enabled and not (lang.is_test_runner(self.test.runner) or self.is_framework_runner):
            raise ValueError(
                f"unknown test runner '{self.test.runner}' for {self.target} "
                f"(expected one of: {', '.join(self.test_runners)})"
            )
        if self.security.codeql and self.platform != "github":
            raise ValueError("security.codeql is only available on GitHub (GitLab: security.sast)")
        if self.security.codeql and not lang.ci.codeql_language:
            raise ValueError(f"CodeQL does not analyze {lang.name}: use security.sast")
        unknown = [s for s in self.security.license_severity if s not in SEVERITIES]
        if unknown:
            raise ValueError(
                f"unknown security.license_severity '{unknown[0]}' (expected some of: {', '.join(SEVERITIES)})"
            )
        if self.security.licenses and not self.security.license_severity:
            raise ValueError("security.license_severity must list at least one level when licenses is true")
        if self.security.sonar and not self.security.sonar_organization:
            raise ValueError("security.sonar_organization is required when security.sonar is enabled")
        if self.build.enabled and not self.build.command:
            raise ValueError("build.command is required when build.enabled is true")
        if not self.branches:
            raise ValueError("branches must contain at least one branch")
        actions = [s.name for s in self.steps if s.uses]
        if actions and self.platform != "github":
            raise ValueError(
                f"step '{actions[0]}' uses a GitHub Action: on GitLab, write it as a job in .gitlab/custom-ci.yml"
            )
        if self.platform == "gitlab" and not self.versions:
            raise ValueError(
                "versions is required on GitLab: jobs run in images chosen by version "
                "(version_file only works with GitHub's setup actions)"
            )
        return self

    @property
    def lint_tools(self) -> List[str]:
        """Lint tools available to this project: the language's, then the framework's."""
        framework = self.get_framework()
        return [*self.language.lint_tools, *(framework.lint_tools if framework else ())]

    @property
    def test_runners(self) -> List[str]:
        framework = self.get_framework()
        return [*self.language.test_runners, *(framework.test_runners if framework else ())]

    def is_lint_tool(self, tool: str) -> bool:
        return self.language.is_lint_tool(tool) or tool in self.lint_tools

    @property
    def is_framework_runner(self) -> bool:
        framework = self.get_framework()
        return framework is not None and self.test.runner in framework.test_runners

    @property
    def matrix(self) -> bool:
        return len(self.versions) > 1


def load_config(project_dir: Path) -> CIConfig:
    return load_section(project_dir, "ci", CIConfig)


def save_config(project_dir: Path, config: CIConfig) -> Path:
    """Write [project] and [ci], preserving any other section already in quoll.toml."""
    return save_section(project_dir, "ci", config)
