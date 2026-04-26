"""The contract every language and framework plugin implements.

A language is a `Language` instance that bundles:
- what identifies it (`markers`) and what quoll.toml may contain for it (package managers, tools);
- `detect`, which inspects a project and returns a `Detection`;
- `ci`, a `CISteps` implementation that turns the validated [ci] config into platform-neutral steps
  (quoll.ci.steps), which each CI platform renders;
- its `frameworks`, tried in order once the language is known.

A framework (`Framework`) refines the language: it adjusts the detection (test runner, tools...) and
can add its own lint tools, test runner, environment and steps through a `FrameworkCI`.

Both can ship a `DockerImage`; a framework's replaces its language's, and `Starter`s creating new projects
(`quoll new`).
"""
from __future__ import annotations

import inspect
import json
import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

from jinja2 import Environment, FileSystemLoader, PrefixLoader, StrictUndefined

from quoll.ci.steps import Cache, Item, Step
from quoll.platforms.base import Remote
from quoll.project import Project
from quoll.services import ServiceEnv, no_service_env

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig
    from quoll.docker.config import DockerConfig

__all__ = ["Cache", "Item", "Step"]

# Languages with `scripts=True` also accept "script:<name>" as a lint tool or test runner.
SCRIPT_PREFIX = "script:"


@dataclass
class Detection:
    """What quoll inferred about a project. Languages fill the toolchain fields; quoll fills the rest."""

    stack: Optional[str] = None
    framework: str = ""
    package_manager: str = ""
    package_manager_version: str = ""
    lockfile: str = ""
    install: str = ""
    cache: bool = True
    version: str = ""
    version_file: str = ""
    matrix_versions: List[str] = field(default_factory=list)
    source_dir: str = "."
    lint_tools: List[str] = field(default_factory=list)
    test_runner: str = ""
    coverage: bool = True
    # The language can run its tests under sanitizers (C/C++).
    sanitizers: bool = False
    # A dependency audit exists for the project (e.g. a lock file the scanner reads).
    audit: bool = True
    build_command: str = ""
    # Backing services the app uses (see quoll.services), from its client libraries.
    services: List[str] = field(default_factory=list)
    # Filled by quoll, not by languages.
    has_dockerfile: bool = False
    # Directory of the project's Helm chart ([k8s] in quoll.toml).
    chart: str = ""
    env_vars: Dict[str, str] = field(default_factory=dict)
    default_branch: str = "main"
    platform: str = "github"
    remote: Optional[Remote] = None
    other_stacks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class CISteps(ABC):
    """CI steps for one language. `cfg` is the validated [ci] section of quoll.toml.

    The toolchain comes from `setup` on GitHub Actions (setup actions on a bare runner) and from `image` plus
    `image_setup` on GitLab CI (jobs run in containers). Every other method returns steps for both: a step that
    uses a GitHub Action must also give the equivalent `run` command.
    """

    # Matrix variable, e.g. "python-version".
    version_key: str = ""
    # False when the audit action installs the toolchain itself (GitHub).
    audit_needs_setup: bool = True
    # CodeQL language (https://codeql.github.com/docs/codeql-overview/supported-languages-and-frameworks/), empty
    # when CodeQL doesn't support it; "autobuild" when the code must be compiled to be analyzed.
    codeql_language: str = ""
    codeql_build_mode: str = "none"

    @abstractmethod
    def setup(self, cfg: CIConfig, version: Optional[str]) -> List[Item]:
        """GitHub Actions steps installing the toolchain. `version` is None when read from `cfg.version_file`."""

    @abstractmethod
    def image(self, cfg: CIConfig, version: str) -> str:
        """Container image providing the toolchain at `version` (which may be a variable such as $NODE_VERSION)."""

    def image_setup(self, cfg: CIConfig) -> List[Step]:
        """Commands completing `image` before the job's steps (package manager, components...)."""
        return []

    def cache(self, cfg: CIConfig) -> Optional[Cache]:
        """Dependency cache of container jobs; on GitHub, `setup` caches."""
        return None

    @abstractmethod
    def install(self, cfg: CIConfig, packages: Sequence[str] = ()) -> List[Item]:
        """Install the project dependencies, plus extra CI-only `packages` where the language supports it."""

    def exec(self, cfg: CIConfig, command: str) -> str:
        """`command` run with the project's installed tools (e.g. `uv run --no-sync`, `npx`)."""
        return command

    @abstractmethod
    def lint(self, cfg: CIConfig, tools: List[str]) -> List[Item]:
        """Install dependencies and run `tools`, a subset of the language's lint tools."""

    @abstractmethod
    def test(self, cfg: CIConfig) -> List[Item]:
        """Install dependencies and run the tests, enforcing the coverage threshold when enabled."""

    @abstractmethod
    def coverage_file(self, cfg: CIConfig) -> str:
        """Coverage report uploaded to Codecov (a glob for some languages)."""

    def reports(self, cfg: CIConfig) -> TestReports:
        """What the test steps leave for the platform to show, when `cfg.test.reports` is on."""
        return TestReports()

    @abstractmethod
    def audit(self, cfg: CIConfig) -> List[Item]:
        """Scan dependencies for known vulnerabilities."""

    @abstractmethod
    def build(self, cfg: CIConfig) -> List[Item]:
        """Run `cfg.build.command`."""

    def build_artifacts(self, det: Detection) -> List[str]:
        """What the detected build command produces, for the build job to keep (nothing if not a distributable)."""
        return []

    @abstractmethod
    def dependabot_ecosystem(self, cfg: CIConfig) -> str:
        """Dependabot `package-ecosystem` for the project's dependencies."""


# Runtime images on Debian or Ubuntu: the security fixes released since the base image was built (the image scan
# fails on them otherwise, and rebuilding picks up the next ones).
OS_UPDATES = """# Security fixes released since the base image was built.
RUN apt-get update \\
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \\
    && rm -rf /var/lib/apt/lists/*"""

# The line printed by quoll's own coverage threshold checks: "Coverage 85.0% (threshold 80%)".
THRESHOLD_REGEX = r"/Coverage (\d+(?:\.\d+)?)% \(threshold/"


@dataclass(frozen=True)
class TestReports:
    __test__ = False  # not a pytest test class

    # JUnit XML results (a glob).
    junit: str = ""
    # Cobertura XML coverage, shown on the diff of merge requests (GitLab).
    cobertura: str = ""
    # Regex extracting the total coverage from the job log (GitLab badge and MR widget).
    coverage_regex: str = ""


class FrameworkCI:
    """Optional framework hooks. The defaults add nothing, so a framework only overrides what it changes."""

    def env(self, cfg: CIConfig) -> Dict[str, str]:
        """Environment variables for the whole workflow."""
        return {}

    def lint(self, cfg: CIConfig, tool: str) -> List[Item]:
        """Steps for one of the framework's lint tools, run after the language's (dependencies installed)."""
        raise NotImplementedError(f"{type(self).__name__} declares lint tool '{tool}' but does not implement it")

    def test(self, cfg: CIConfig) -> List[Item]:
        """Full test steps when `cfg.test.runner` is one of the framework's test runners."""
        raise NotImplementedError(f"{type(self).__name__} declares a test runner but does not implement it")

    def before_build(self, cfg: CIConfig) -> List[Item]:
        """Steps before the build (e.g. a framework build cache)."""
        return []


@dataclass
class DockerDefaults:
    """What an image infers from the project; becomes the [docker] section of quoll.toml."""

    port: int
    command: str = ""
    build_command: str = ""
    output_dir: str = ""
    static: bool = False
    warnings: List[str] = field(default_factory=list)


class DockerImage(ABC):
    """A Dockerfile, rendered from the `Dockerfile.j2` next to the class (or its closest parent's).

    Images inherit like their classes. A framework image subclasses its language's: it overrides `defaults`
    (port, command) or `context`, and when the image itself differs, ships a Dockerfile.j2 that extends the
    language's and overrides only the stages (blocks) that change:

        {% extends "node/Dockerfile.j2" %}
        {% block app_files %}...{% endblock %}

    Templates are addressed as "<directory>/Dockerfile.j2", e.g. "node/Dockerfile.j2".
    """

    # False when the base image already runs a server (e.g. FrankenPHP).
    requires_command: bool = True

    @abstractmethod
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        """Port, start command and build settings inferred from the project."""

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        """Template variables besides `cfg`."""
        return {}

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        """Patterns to keep out of the build context, on top of the common ones."""
        return []

    def writable_paths(self, cfg: DockerConfig) -> Optional[List[str]]:
        """Directories the app writes to: Kubernetes mounts them on a read-only root filesystem. None: the app
        writes in its own tree, the root filesystem stays writable."""
        return ["/tmp"]

    def render(self, project: Project, cfg: DockerConfig) -> str:
        dirs = self._template_dirs()
        env = Environment(
            loader=PrefixLoader({d.name: FileSystemLoader(str(d)) for d in dirs}),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )
        env.filters["exec_form"] = exec_form
        env.globals["os_updates"] = OS_UPDATES
        return env.get_template(f"{dirs[0].name}/Dockerfile.j2").render(cfg=cfg, **self.context(project, cfg))

    def _template_dirs(self) -> List[Path]:
        """Directories holding a Dockerfile.j2, from this class up to its oldest ancestor."""
        dirs: List[Path] = []
        for cls in type(self).__mro__:
            if cls in (DockerImage, ABC, object):
                continue
            directory = Path(inspect.getfile(cls)).parent
            if (directory / "Dockerfile.j2").exists() and directory not in dirs:
                dirs.append(directory)
        return dirs


def exec_form(command: str) -> str:
    """JSON (exec) form of a command, so the process receives signals; through `sh -c` if it needs a shell."""
    if any(c in command for c in "$&|;<>*`") or "\n" in command:
        return json.dumps(["sh", "-c", command])
    return json.dumps(shlex.split(command))


@dataclass(frozen=True)
class StarterOptions:
    # Package name of the new project.
    name: str
    # Version of the framework, e.g. "18" for Angular 18 (empty: the latest).
    version: str = ""
    # Version of the language's runtime, e.g. "20" for Node.js 20 (empty: the starter's default).
    runtime: str = ""


@dataclass(frozen=True)
class Starter:
    """Creates a new project in an empty directory (see quoll.starters for templates and generators)."""

    # Key used on the command line: `quoll new --front angular` (`angular@18` for a version).
    name: str
    label: str
    # Where it fits in a front-end + back-end repository: "front" or "back".
    role: str
    # (directory, options) -> warnings for the user (e.g. an unsupported version). The directory exists, empty.
    create: Callable[[Path, StarterOptions], Optional[List[str]]]
    # The runtime `runtime` options are for: `quoll new --node 20`.
    runtime: str = ""
    runtime_default: str = ""
    # Front-ends: (directory, path, url) makes the dev server forward `path` (e.g. "/api") to the API at `url`, as
    # nginx does in the image ([docker] proxy).
    proxy: Optional[Callable[[Path, str, str], None]] = None


@dataclass(frozen=True)
class Framework:
    name: str
    # Name of the language it belongs to.
    language: str
    # Returns True when the framework is used, and may refine the detection (tools, test runner...).
    detect: Callable[[Project, Detection], bool]
    ci: FrameworkCI = field(default_factory=FrameworkCI)
    lint_tools: Tuple[str, ...] = ()
    test_runners: Tuple[str, ...] = ()
    # Replaces the language's image when set.
    docker: Optional[DockerImage] = None
    # Extra variables pointing the app at a service, e.g. Laravel's DB_HOST.
    service_env: ServiceEnv = no_service_env
    starters: Tuple[Starter, ...] = ()


@dataclass(frozen=True)
class Language:
    name: str
    # Any of these files (or glob patterns) at the project root identifies the language.
    markers: Tuple[str, ...]
    package_managers: Tuple[str, ...]
    lint_tools: Tuple[str, ...]
    test_runners: Tuple[str, ...]
    detect: Callable[[Project], Detection]
    ci: CISteps
    # Tried in order: the first whose detect() returns True is the project's framework.
    frameworks: Tuple[Framework, ...] = ()
    scripts: bool = False
    docker: Optional[DockerImage] = None
    # Extra variables pointing the app at a service, e.g. Spring's datasource URL.
    service_env: ServiceEnv = no_service_env
    starters: Tuple[Starter, ...] = ()

    def matches(self, project: Project) -> bool:
        return project.glob_any(*self.markers)

    def is_lint_tool(self, value: str) -> bool:
        return value in self.lint_tools or self._is_script(value)

    def is_test_runner(self, value: str) -> bool:
        return value in self.test_runners or self._is_script(value)

    def _is_script(self, value: str) -> bool:
        return self.scripts and value.startswith(SCRIPT_PREFIX) and len(value) > len(SCRIPT_PREFIX)
