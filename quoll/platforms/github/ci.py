"""Turn a CIConfig into GitHub Actions files."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from jinja2 import Environment, FileSystemLoader

from quoll.ci import custom
from quoll.ci.config import SECURITY_JOBS, CIConfig
from quoll.ci.steps import Item, step
from quoll.ci.tools import (
    GITLEAKS_IMAGE,
    SBOM_FILE,
    SEMGREP_IMAGE,
    dependency_checks,
    image_checks,
    sast,
    secret_scan,
)
from quoll.files import PlannedFile, header, planned
from quoll.k8s.ci import HELM_VERSION, chart_checks
from quoll.languages.base import FrameworkCI
from quoll.platforms.github.actions import ACTIONS, gha_cache_scope
from quoll.platforms.github.platform import GATE_CHECK
from quoll.platforms.github.workflow import checkout, dump, render_steps
from quoll.services import SERVICES
from quoll.workspace import Member, Repo

WORKFLOW_PATH = Path(".github/workflows/ci.yml")
DEPENDABOT_PATH = Path(".github/dependabot.yml")
# For your own workflows: `- uses: ./.github/actions/quoll-setup` after the checkout (one per member of a
# workspace: quoll-setup-<member>).
SETUP_ACTION_PATH = Path(".github/actions/quoll-setup/action.yml")


def render_workflow(target: Union[CIConfig, Repo]) -> str:
    """The CI workflow of a project, or of a workspace (one set of jobs per member, run when it changed)."""
    repo = target if isinstance(target, Repo) else Repo.single(target)
    jobs: Dict[str, Any] = {}
    if repo.workspace:
        jobs["changes"] = _changes_job(repo)
    for member in repo.members:
        member_jobs = _project_jobs(member, repo)
        if repo.workspace:
            member_jobs = {
                name: _guard(job, [f"needs.changes.outputs.{member.name} == 'true'"], needs=["changes"])
                for name, job in member_jobs.items()
            }
        jobs.update(member_jobs)
    if repo.workspace:
        # Repository-wide scans, once.
        jobs.update(_repo_jobs(repo))
    if not [name for name in jobs if name != "changes"]:
        raise ValueError("every CI job is disabled — enable at least one in quoll.toml")

    if repo.schedule.enabled:
        # Scheduled runs only re-check security: the code didn't change, the vulnerability databases did.
        jobs = {
            name: job if name == "changes" or _kind(name, repo) in SECURITY_JOBS else _skip_on_schedule(job)
            for name, job in jobs.items()
        }

    jobs["ci-result"] = {
        "name": GATE_CHECK,
        "if": "${{ always() }}",
        "needs": list(jobs),
        "runs-on": "ubuntu-latest",
        "timeout-minutes": 5,
        "steps": [
            {
                "name": "Check job results",
                "if": "${{ contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled') }}",
                "run": "exit 1",
            }
        ],
    }

    doc: Dict[str, Any] = {
        "name": "CI",
        "on": {
            "push": {"branches": list(repo.branches)},
            "pull_request": None,
            "merge_group": None,
            **({"schedule": [{"cron": repo.schedule.cron}]} if repo.schedule.enabled else {}),
            "workflow_dispatch": None,
        },
        "permissions": {"contents": "read"},
        "concurrency": {
            "group": "${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}",
            "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
        },
    }
    if not repo.workspace:
        env = _framework_env(repo.members[0].cfg)
        if env:
            doc["env"] = env
    doc["jobs"] = jobs
    return header("ci") + dump(doc)


def _project_jobs(member: Member, repo: Repo) -> Dict[str, Any]:
    """The jobs of one project. Alone in the repository, it also carries the repository-wide scans, in their
    historical place."""
    cfg = member.cfg
    ci = cfg.language.ci
    framework = cfg.get_framework()
    framework_ci = framework.ci if framework else FrameworkCI()
    default_version = cfg.versions[-1] if cfg.versions else None
    directory = cfg.directory
    # In a workspace, each project's framework settings go to its own jobs.
    env = _framework_env(cfg) if repo.workspace else None
    jobs: Dict[str, Any] = {}

    def add(kind: str, label: str, timeout: int, steps: Sequence[Item], **options: Any) -> None:
        name = f"{member.name}: {label}" if member.name else label
        options["env"] = {**(env or {}), **(options.get("env") or {})} or None
        jobs[member.job(kind)] = _job(name, timeout, steps, directory=directory, **options)

    if cfg.lint.enabled and cfg.lint.tools:
        own = [t for t in cfg.lint.tools if cfg.language.is_lint_tool(t)]
        lint: List[Item] = list(ci.lint(cfg, own))
        for tool in cfg.lint.tools:
            if tool not in own:
                lint.extend(framework_ci.lint(cfg, tool))
        add("lint", "Lint", 10, [checkout(), *ci.setup(cfg, default_version), *custom.extend(cfg, "lint", lint)])

    if cfg.test.enabled:
        service_env = cfg.service_environment("127.0.0.1")
        if service_env:
            # The test databases win over secrets of the same name: tests must never hit a real database.
            secrets = [s for s in cfg.test.env_secrets if s not in service_env]
            cfg = cfg.model_copy(update={"test": cfg.test.model_copy(update={"env_secrets": secrets})})
        options: Dict[str, Any] = {}
        if cfg.services:
            options["services"] = _service_containers(cfg)
            options["env"] = service_env
        label = "Test"
        version = default_version
        if cfg.matrix:
            key = ci.version_key
            label = f"Test (${{{{ matrix.{key} }}}})"
            version = f"${{{{ matrix.{key} }}}}"
            options["strategy"] = {"fail-fast": False, "matrix": {key: list(cfg.versions)}}
        tests = framework_ci.test(cfg) if cfg.is_framework_runner else ci.test(cfg)
        steps: List[Item] = [checkout(), *ci.setup(cfg, version), *custom.extend(cfg, "test", tests)]
        junit = ci.reports(cfg).junit if cfg.test.reports else ""
        if junit:
            # Failed tests annotated on the pull request, results in the job summary.
            steps.append(
                step(
                    "Test report",
                    uses=ACTIONS["junit-report"],
                    with_={"report_paths": cfg.path(junit), "annotate_only": True, "detailed_summary": True},
                    always=True,
                )
            )
        if cfg.test.coverage and cfg.test.codecov:
            steps.append(
                step(
                    "Upload coverage to Codecov",
                    uses=ACTIONS["codecov"],
                    with_={"files": cfg.path(ci.coverage_file(cfg)), "token": "${{ secrets.CODECOV_TOKEN }}"},
                    always=True,
                )
            )
        add("test", label, 20, steps, **options)

    if cfg.security.audit:
        setup = ci.setup(cfg, default_version) if ci.audit_needs_setup else []
        add("audit", "Dependency audit", 10, [checkout(), *setup, *custom.extend(cfg, "audit", ci.audit(cfg))])

    if not repo.workspace and repo.secrets:
        jobs["secrets"] = _secrets_job()

    if cfg.security.sbom or cfg.security.licenses:
        sec = cfg.security
        sbom_steps: List[Item] = [
            checkout(),
            *ci.setup(cfg, default_version),
            *custom.extend(
                cfg, "sbom", [*ci.install(cfg), *dependency_checks(sec.sbom, sec.licenses, sec.license_severity)]
            ),
        ]
        if sec.sbom:
            artifact = f"{member.name}-sbom" if member.name else "sbom"
            sbom_steps.append(
                step(
                    "Upload SBOM",
                    uses=ACTIONS["upload-artifact"],
                    with_={"name": artifact, "path": cfg.path(SBOM_FILE)},
                    always=True,
                )
            )
        add("sbom", "SBOM and licenses" if sec.licenses else "SBOM", 15, sbom_steps)

    if not repo.workspace and repo.sast:
        jobs["sast"] = _sast_job()

    if cfg.security.codeql:
        init: Dict[str, Any] = {"languages": ci.codeql_language, "build-mode": ci.codeql_build_mode}
        if directory != ".":
            init["source-root"] = directory
        codeql_steps: List[Item] = [checkout()]
        if ci.codeql_build_mode != "none":
            codeql_steps += ci.setup(cfg, default_version)
        codeql_steps.append(step("Initialize CodeQL", uses=ACTIONS["codeql-init"], with_=init))
        if ci.codeql_build_mode == "manual":
            # CodeQL watches the language's own build.
            codeql_steps += ci.build(cfg)
        codeql_steps.append(step("Analyze", uses=ACTIONS["codeql-analyze"]))
        add("codeql", "CodeQL", 30, codeql_steps, permissions={"contents": "read", "security-events": "write"})

    if cfg.security.sonar:
        sonar = step(
            "SonarCloud scan",
            uses=ACTIONS["sonar"],
            with_=_sonar_inputs(cfg),
            env={"SONAR_TOKEN": "${{ secrets.SONAR_TOKEN }}"},
        )
        add(
            "sonar",
            "SonarCloud",
            15,
            [checkout(fetch_depth=0), sonar],
            # Secrets are not available to pull requests from forks.
            if_=(
                "${{ github.event_name != 'pull_request' || "
                "github.event.pull_request.head.repo.full_name == github.repository }}"
            ),
        )

    if cfg.build.enabled:
        build_steps = [*framework_ci.before_build(cfg), *ci.build(cfg)]
        build_steps = custom.extend(cfg, "build", build_steps)
        if cfg.build.artifacts:
            build_steps.append(step("Keep the build output", uses=ACTIONS["upload-artifact"], with_={
                "name": member.job("build"),
                "path": "\n".join(cfg.path(p) for p in cfg.build.artifacts),
                "retention-days": 7,
            }))
        add("build", "Build", 15, [checkout(), *ci.setup(cfg, default_version), *build_steps])

    if cfg.build.chart:
        helm = step("Set up Helm", uses=ACTIONS["setup-helm"], with_={"version": f"v{HELM_VERSION}"})
        add("chart", "Helm chart", 10, [checkout(), helm, *chart_checks(cfg.build.chart)])

    if cfg.build.docker:
        tag = f"{member.name or 'ci'}:${{{{ github.sha }}}}"
        lint_image, build, scan = image_checks(tag)
        build = step(
            build.name,
            uses=ACTIONS["build-push"],
            with_={
                "context": directory,
                "load": True,
                "tags": tag,
                "cache-from": gha_cache_scope(member.name),
                "cache-to": f"{gha_cache_scope(member.name)},mode=max",
            },
        )
        add(
            "docker",
            "Docker image",
            20,
            [checkout(), step("Set up Docker Buildx", uses=ACTIONS["setup-buildx"]), lint_image, build, scan],
        )
    return jobs


def _repo_jobs(repo: Repo) -> Dict[str, Any]:
    jobs: Dict[str, Any] = {}
    if repo.secrets:
        jobs["secrets"] = _secrets_job()
    if repo.sast:
        jobs["sast"] = _sast_job()
    return jobs


def _secrets_job() -> Dict[str, Any]:
    return _job("Secret scanning", 10, [checkout(fetch_depth=0), secret_scan()], container=GITLEAKS_IMAGE)


def _sast_job() -> Dict[str, Any]:
    return _job("Static analysis", 15, [checkout(), sast()], container=SEMGREP_IMAGE)


# Whatever touches every member: the workspace's quoll.toml and the CI itself.
_SHARED_PATHS = r"quoll\.toml$|\.github/"

_CHANGES = """case "$EVENT" in
  pull_request) base="$PR_BASE" ;;
  merge_group) base="$QUEUE_BASE" ;;
  push) base="$PUSH_BEFORE" ;;
  *) base="" ;;
esac
# A new branch, a scheduled or a manual run: everything counts as changed.
if [ -n "$base" ] && git cat-file -e "$base^{commit}" 2>/dev/null; then
  changed=$(git diff --name-only "$base" HEAD)
else
  changed=$(git ls-files)
fi
check() {
  if printf '%s\\n' "$changed" | grep -qE "$2"; then echo "$1=true"; else echo "$1=false"; fi >> "$GITHUB_OUTPUT"
  grep "^$1=" "$GITHUB_OUTPUT"
}"""


def _changes_job(repo: Repo) -> Dict[str, Any]:
    """Which members a push or a pull request touches: the others' jobs are skipped."""
    checks = []
    for member in repo.members:
        directory = member.directory
        own = "" if directory == "." else re.escape(directory) + "/|"
        pattern = "." if directory == "." else f"^({own}{_SHARED_PATHS})"
        checks.append(f"check {member.name} '{pattern}'")
    detect = step(
        "Changed projects",
        run=_CHANGES + "\n" + "\n".join(checks),
        id_="diff",
        env={
            "EVENT": "${{ github.event_name }}",
            "PR_BASE": "${{ github.event.pull_request.base.sha }}",
            "QUEUE_BASE": "${{ github.event.merge_group.base_sha }}",
            "PUSH_BEFORE": "${{ github.event.before }}",
        },
    )
    job = _job("Changes", 5, [checkout(fetch_depth=0), detect])
    outputs = {m.name: f"${{{{ steps.diff.outputs.{m.name} }}}}" for m in repo.members}
    return {k: v for k, v in [*list(job.items())[:3], ("outputs", outputs), *list(job.items())[3:]]}


def _kind(job: str, repo: Repo) -> str:
    """The generated job a (possibly prefixed) job name stands for: backend-test -> test."""
    for member in repo.members:
        if member.name and job.startswith(f"{member.name}-"):
            return job[len(member.name) + 1 :]
    return job


def _framework_env(cfg: CIConfig) -> Dict[str, str]:
    framework = cfg.get_framework()
    return (framework.ci if framework else FrameworkCI()).env(cfg)


def render_dependabot(target: Union[CIConfig, Repo], docker: Sequence[str] = ()) -> str:
    """Dependency, GitHub Actions and base image updates (in `docker`, the directories holding a Dockerfile)."""
    repo = target if isinstance(target, Repo) else Repo.single(target)
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent)), keep_trailing_newline=True, trim_blocks=True
    )
    ecosystems = []
    for member in repo.members:
        ecosystem = member.cfg.language.ci.dependabot_ecosystem(member.cfg)
        if ecosystem:
            ecosystems.append((ecosystem, _dependabot_directory(member.directory)))
    directories = [_dependabot_directory(d) for d in docker]
    return env.get_template("dependabot.yml.j2").render(ecosystems=ecosystems, docker=directories)


def _dependabot_directory(directory: str) -> str:
    return "/" if directory == "." else f"/{directory}"


def setup_action_path(member: Member) -> Path:
    name = f"quoll-setup-{member.name}" if member.name else "quoll-setup"
    return Path(f".github/actions/{name}/action.yml")


def render_setup_action(cfg: CIConfig) -> str:
    """A composite action giving your own jobs the project's environment: toolchain, caches, dependencies."""
    ci = cfg.language.ci
    action: Dict[str, Any] = {
        "name": "quoll setup",
        "description": f"Set up {cfg.target} and install the dependencies, as quoll's CI does. Use after checkout.",
    }
    if cfg.versions:
        action["inputs"] = {
            "version": {
                "description": f"{ci.version_key} (default: the latest of [ci] versions)",
                "default": cfg.versions[-1],
            }
        }
        version: Optional[str] = "${{ inputs.version }}"
    else:
        version = None  # read from [ci] version_file
    steps = render_steps([*ci.setup(cfg, version), *ci.install(cfg)], cfg.directory)
    # Composite actions name the shell (and the directory) of each command.
    where = {"working-directory": cfg.directory} if cfg.directory != "." else {}
    action["runs"] = {
        "using": "composite",
        "steps": [{**s, "shell": "bash", **where} if "run" in s else s for s in steps],
    }
    env = (cfg.get_framework().ci if cfg.get_framework() else FrameworkCI()).env(cfg)
    if env:
        settings = {"name": "Framework settings", "run": _export_env(env), "shell": "bash", **where}
        action["runs"]["steps"].insert(0, settings)
    return header("ci") + dump(action)


def _export_env(env: Dict[str, str]) -> str:
    return "\n".join(f'echo "{k}={v}" >> "$GITHUB_ENV"' for k, v in env.items())


def plan(project_dir: Path, target: Union[CIConfig, Repo]) -> List[PlannedFile]:
    repo = target if isinstance(target, Repo) else Repo.single(target)
    files = [planned(project_dir, WORKFLOW_PATH, render_workflow(repo))]
    files += [planned(project_dir, setup_action_path(m), render_setup_action(m.cfg)) for m in repo.members]
    # Dependabot config is often customised by hand: only create it, never overwrite it.
    if repo.dependency_updates and not (project_dir / DEPENDABOT_PATH).exists():
        docker = [m.directory for m in repo.members if (project_dir / m.directory / "Dockerfile").exists()]
        files.append(planned(project_dir, DEPENDABOT_PATH, render_dependabot(repo, docker), create_only=True))
    return files


def _job(
    name: str,
    timeout: int,
    steps: Sequence[Item],
    *,
    container: Optional[str] = None,
    permissions: Optional[Dict[str, str]] = None,
    if_: Optional[str] = None,
    strategy: Optional[Dict[str, Any]] = None,
    services: Optional[Dict[str, Any]] = None,
    env: Optional[Dict[str, str]] = None,
    directory: str = ".",
) -> Dict[str, Any]:
    job: Dict[str, Any] = {"name": name}
    if if_:
        job["if"] = if_
    job["runs-on"] = "ubuntu-latest"
    if container:
        job["container"] = container
    if permissions:
        job["permissions"] = permissions
    job["timeout-minutes"] = timeout
    if strategy:
        job["strategy"] = strategy
    if services:
        job["services"] = services
    if env:
        job["env"] = env
    if directory != ".":
        # Commands run in the project's directory; actions' paths are given from the repository root.
        job["defaults"] = {"run": {"working-directory": directory}}
    job["steps"] = render_steps(steps, directory)
    return job


def _skip_on_schedule(job: Dict[str, Any]) -> Dict[str, Any]:
    return _guard(job, ["github.event_name != 'schedule'"])


def _guard(job: Dict[str, Any], conditions: List[str], needs: Optional[List[str]] = None) -> Dict[str, Any]:
    """`job` running only when `conditions` hold (after `needs`), on top of its own condition (e.g. SonarCloud's
    fork check)."""
    current = job.get("if", "")
    if current:
        conditions = [*conditions, f"({current[len('${{ '):-len(' }}')]})"]
    rest = {k: v for k, v in job.items() if k not in ("name", "needs", "if")}
    guarded: Dict[str, Any] = {"name": job["name"]}
    all_needs = [*(needs or []), *[n for n in job.get("needs", []) if n not in (needs or [])]]
    if all_needs:
        guarded["needs"] = all_needs
    guarded["if"] = "${{ " + " && ".join(conditions) + " }}"
    guarded.update(rest)
    return guarded


def _service_containers(cfg: CIConfig) -> Dict[str, Any]:
    containers: Dict[str, Any] = {}
    for name in cfg.services:
        service = SERVICES[name]
        container: Dict[str, Any] = {"image": service.image}
        if service.env:
            container["env"] = service.env
        container["ports"] = [f"{service.port}:{service.port}"]
        # Steps start once the service is healthy.
        container["options"] = (
            f'--health-cmd "{service.health}" --health-interval 5s --health-timeout 5s --health-retries 20'
        )
        containers[name] = container
    return containers


def _sonar_inputs(cfg: CIConfig) -> Dict[str, Any]:
    args = f"-Dsonar.organization={cfg.security.sonar_organization}"
    if cfg.security.sonar_project_key:
        args = f"-Dsonar.projectKey={cfg.security.sonar_project_key} {args}"
    inputs: Dict[str, Any] = {"args": args}
    if cfg.directory != ".":
        inputs["projectBaseDir"] = cfg.directory
    return inputs
