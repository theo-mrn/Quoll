"""Turn a CIConfig into .gitlab-ci.yml (and a Renovate config)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

from quoll.ci import custom
from quoll.ci.config import SECURITY_JOBS, CIConfig
from quoll.ci.steps import Item, Step, step
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
from quoll.k8s.ci import HELM_IMAGE, chart_checks
from quoll.languages.base import FrameworkCI
from quoll.platforms.gitlab.pipeline import branch_rule, docker_job, dump, job, registry_cache, variable_name
from quoll.services import SERVICES
from quoll.workspace import Member, Repo

PIPELINE_PATH = Path(".gitlab-ci.yml")
# quoll's jobs, included by .gitlab-ci.yml.
JOBS_PATH = ".gitlab/quoll-ci.yml"
# Template of the project's environment for your own jobs.
SETUP_TEMPLATE = ".quoll-setup"
SCHEDULED = '$CI_PIPELINE_SOURCE == "schedule"'
# Your own jobs and overrides of quoll's, included last when present: quoll never touches it.
CUSTOM_PATH = ".gitlab/custom-ci.yml"
# Written by `quoll cd`, included when present.
CD_PATH = ".gitlab/cd.yml"
RENOVATE_PATH = Path("renovate.json")
# Any of these means Renovate is already configured.
RENOVATE_CONFIGS = ("renovate.json", "renovate.json5", ".renovaterc", ".renovaterc.json", ".gitlab/renovate.json")
SONAR_IMAGE = "sonarsource/sonar-scanner-cli:12"
SAST_REPORT = "gl-sast-report.json"
_INFRASTRUCTURE_FAILURES = (
    "runner_system_failure", "stuck_or_timeout_failure", "api_failure", "scheduler_failure", "data_integrity_failure"
)
CODECOV_IMAGE = "python:3"
# CI jobs run in `test`; the delivery publishes once they all passed.
STAGES = ["test", "publish", "deploy"]


def render_pipeline(target: Union[CIConfig, Repo]) -> str:
    """.gitlab/quoll-ci.yml: the jobs of a project, or of every member of a workspace (run when it changed)."""
    repo = target if isinstance(target, Repo) else Repo.single(target)
    jobs: Dict[str, Any] = {}
    templates: Dict[str, Any] = {}
    for member in repo.members:
        member_jobs, template = _project_jobs(member, repo)
        if repo.workspace:
            member_jobs = {name: _on_changes(j, member) for name, j in member_jobs.items()}
        jobs.update(member_jobs)
        templates[_template_name(member)] = template
    if repo.workspace:
        # Repository-wide scans, once.
        jobs.update(_repo_jobs(repo))
    if not jobs:
        raise ValueError("every CI job is disabled — enable at least one in quoll.toml")

    if repo.schedule.enabled:
        # Scheduled pipelines (a GitLab pipeline schedule, see `quoll ci schedule`) only re-check security.
        jobs = {name: j if _kind(name, repo) in SECURITY_JOBS else _skip_on_schedule(j) for name, j in jobs.items()}

    doc: Dict[str, Any] = {}
    if not repo.workspace:
        env = _framework_env(repo.members[0].cfg)
        if env:
            doc["variables"] = env
    doc["default"] = {"interruptible": True}
    doc.update(templates)
    doc.update(jobs)
    return header("ci") + dump(doc)


def _project_jobs(member: Member, repo: Repo) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The jobs of one project and its setup template. Alone in the repository, it also carries the
    repository-wide scans, in their historical place."""
    cfg = member.cfg
    ci = cfg.language.ci
    framework = cfg.get_framework()
    framework_ci = framework.ci if framework else FrameworkCI()
    version = cfg.versions[-1]
    image = ci.image(cfg, version)
    setup = ci.image_setup(cfg)
    cache = ci.cache(cfg)
    caches = [cache] if cache else []
    directory = cfg.directory
    # In a workspace, each project's framework settings go to its own jobs.
    env = _framework_env(cfg) if repo.workspace else {}
    jobs: Dict[str, Any] = {}

    def project_job(items: List[Item], **options: Any) -> Dict[str, Any]:
        variables = {**env, **options.pop("variables", {})}
        return job(
            "test", options.pop("image", image), items, directory=directory, variables=variables or None, **options
        )

    if cfg.lint.enabled and cfg.lint.tools:
        own = [t for t in cfg.lint.tools if cfg.language.is_lint_tool(t)]
        items: List[Item] = list(ci.lint(cfg, own))
        for tool in cfg.lint.tools:
            if tool not in own:
                items.extend(framework_ci.lint(cfg, tool))
        items = custom.extend(cfg, "lint", items)
        jobs[member.job("lint")] = project_job(items, setup=setup, caches=caches, timeout=10)

    if cfg.test.enabled:
        tests = custom.extend(cfg, "test", framework_ci.test(cfg) if cfg.is_framework_runner else ci.test(cfg))
        test_setup = list(setup)
        options: Dict[str, Any] = {}
        if cfg.matrix:
            # Each entry carries its resolved image: versions may be aliases (stable, lts...) of other tags.
            variable = variable_name(ci.version_key)
            options["image"] = "$IMAGE"
            options["parallel"] = {"matrix": [{variable: v, "IMAGE": ci.image(cfg, v)} for v in cfg.versions]}
        if cfg.services:
            options["services"] = _services(cfg)
            # Exported by the script rather than set as job variables, which project CI/CD variables of the same
            # name would override: tests must never hit a real database.
            test_setup.insert(0, _export_step(cfg.service_environment(lambda name: name)))
        artifacts = _test_artifacts(cfg)
        if artifacts:
            options["artifacts"] = artifacts
        test = project_job(tests, setup=test_setup, caches=caches, timeout=20, **options)
        regex = ci.reports(cfg).coverage_regex if cfg.test.reports else ""
        if regex:
            # Total coverage parsed from the log: merge request widget and badge.
            test["coverage"] = regex
        jobs[member.job("test")] = test
        if cfg.test.coverage and cfg.test.codecov:
            jobs[member.job("codecov")] = job(
                "test",
                CODECOV_IMAGE,
                [_codecov_step(cfg.path(ci.coverage_file(cfg)))],
                needs=[{"job": member.job("test"), "artifacts": True}],
                rules=[{"if": "$CODECOV_TOKEN", "when": "always"}],
                timeout=5,
            )

    if cfg.security.audit:
        audit = custom.extend(cfg, "audit", ci.audit(cfg))
        jobs[member.job("audit")] = project_job(audit, setup=setup, caches=caches, timeout=10)

    if not repo.workspace and repo.secrets:
        jobs["secrets"] = _secrets_job()

    if cfg.security.sbom or cfg.security.licenses:
        sec = cfg.security
        items = [*ci.install(cfg), *dependency_checks(sec.sbom, sec.licenses, sec.license_severity)]
        items = custom.extend(cfg, "sbom", items)
        sbom_job = project_job(items, setup=setup, caches=caches, timeout=15)
        if sec.sbom:
            # The dependency list of the project (GitLab Ultimate), and the file to download on every tier.
            sbom = cfg.path(SBOM_FILE)
            sbom_job["artifacts"] = {
                "when": "always",
                "paths": [sbom],
                "reports": {"cyclonedx": [sbom]},
                "expire_in": "1 week",
            }
        jobs[member.job("sbom")] = sbom_job

    if not repo.workspace and repo.sast:
        jobs["sast"] = _sast_job()

    if cfg.security.sonar:
        sonar = _tool_job(
            SONAR_IMAGE,
            [step("SonarCloud scan", run=_sonar_command(cfg))],
            # Masked variables are not available to merge requests from forks.
            rules=[{"if": "$SONAR_TOKEN"}],
            variables={
                "SONAR_HOST_URL": "https://sonarcloud.io",
                "SONAR_USER_HOME": "$CI_PROJECT_DIR/.sonar",
                "GIT_DEPTH": "0",
            },
            timeout=15,
        )
        sonar["cache"] = [{"key": "sonar", "paths": [".sonar/cache"]}]
        jobs[member.job("sonar")] = sonar

    if cfg.build.enabled:
        items = custom.extend(cfg, "build", [*framework_ci.before_build(cfg), *ci.build(cfg)])
        kept = {"paths": [cfg.path(p) for p in cfg.build.artifacts], "expire_in": "1 week"}
        jobs[member.job("build")] = project_job(
            items, setup=setup, caches=caches, timeout=15, artifacts=kept if cfg.build.artifacts else None
        )

    if cfg.build.docker:
        project = member.name or "ci"
        tag = f"{project}:$CI_COMMIT_SHA"
        lint_image, _, scan = image_checks(tag)
        build = registry_cache(project) + f'\ndocker buildx build --load $cache --tag "{tag}" .'
        checks = [lint_image.run, build, scan.run]
        jobs[member.job("docker")] = docker_job("test", checks, timeout=20, directory=directory)

    if cfg.build.chart:
        jobs[member.job("chart")] = _tool_job(HELM_IMAGE, list(chart_checks(cfg.build.chart)), timeout=10,
                                              directory=directory)

    return jobs, _setup_template(cfg, image, setup, caches, env)


def _repo_jobs(repo: Repo) -> Dict[str, Any]:
    jobs: Dict[str, Any] = {}
    if repo.secrets:
        jobs["secrets"] = _secrets_job()
    if repo.sast:
        jobs["sast"] = _sast_job()
    return jobs


def _secrets_job() -> Dict[str, Any]:
    return _tool_job(
        GITLEAKS_IMAGE,
        # The runner's clone belongs to another user than the image's: let git read it.
        [step("Trust the clone", run='git config --global --add safe.directory "$CI_PROJECT_DIR"'), secret_scan()],
        variables={"GIT_DEPTH": "0"},
        timeout=10,
    )


def _sast_job() -> Dict[str, Any]:
    sast_job = _tool_job(SEMGREP_IMAGE, [sast(report=SAST_REPORT)], timeout=15)
    # Findings in the merge request's security widget (GitLab Ultimate); the job fails on them on every tier.
    sast_job["artifacts"] = {"when": "always", "reports": {"sast": SAST_REPORT}}
    return sast_job


def _on_changes(j: Dict[str, Any], member: Member) -> Dict[str, Any]:
    """`j` only when the member's files (or what every member shares) changed. Tags, schedules and manual runs
    count everything as changed."""
    paths = {"paths": [f"{member.directory}/**/*", *_SHARED_PATHS]} if member.directory != "." else None
    if paths is None:
        return j
    rules = [{**rule, "changes": paths} for rule in j.get("rules", [{"when": "on_success"}])]
    rest = {k: v for k, v in j.items() if k not in ("stage", "image", "rules")}
    return {"stage": j["stage"], "image": j["image"], "rules": rules, **rest}


# Whatever touches every member: the workspace's quoll.toml and the CI itself.
_SHARED_PATHS = ["quoll.toml", ".gitlab-ci.yml", ".gitlab/**/*"]


def _template_name(member: Member) -> str:
    return f"{SETUP_TEMPLATE}-{member.name}" if member.name else SETUP_TEMPLATE


def _kind(job_name: str, repo: Repo) -> str:
    """The generated job a (possibly prefixed) job name stands for: backend-test -> test."""
    for member in repo.members:
        if member.name and job_name.startswith(f"{member.name}-"):
            return job_name[len(member.name) + 1 :]
    return job_name


def _framework_env(cfg: CIConfig) -> Dict[str, str]:
    framework = cfg.get_framework()
    return (framework.ci if framework else FrameworkCI()).env(cfg)


def render_root(target: Union[CIConfig, Repo]) -> str:
    """.gitlab-ci.yml: when pipelines run, and what they include. quoll's jobs come first, so that
    .gitlab/custom-ci.yml, included last, can add jobs and override any key of quoll's."""
    repo = target if isinstance(target, Repo) else Repo.single(target)
    doc: Dict[str, Any] = {
        "workflow": {
            "rules": [
                {"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'},
                *(branch_rule(b) for b in repo.branches),
                {"if": "$CI_COMMIT_TAG"},
                {"if": '$CI_PIPELINE_SOURCE == "web"'},
                *([{"if": SCHEDULED}] if repo.schedule.enabled else []),
            ],
            # A new commit cancels the running pipeline of the same branch (the delivery is not interruptible).
            "auto_cancel": {"on_new_commit": "interruptible"},
        },
        "stages": STAGES,
        # A job lost to the infrastructure (runner, timeout, API) runs again; a failing test doesn't (a retry would
        # hide a flaky one).
        "default": {"retry": {"max": 2, "when": list(_INFRASTRUCTURE_FAILURES)}},
        "include": [
            {"local": JOBS_PATH},
            *({"local": path, "rules": [{"exists": [path]}]} for path in (CD_PATH, CUSTOM_PATH)),
        ],
    }
    return header("ci") + dump(doc)


def _setup_template(cfg: CIConfig, image: str, setup: List[Step], caches: list, env: Dict[str, str]) -> Dict[str, Any]:
    """For your own jobs (`extends: .quoll-setup`): the project's image, caches and installed dependencies,
    commands run in its directory."""
    template = job(
        "test",
        image,
        cfg.language.ci.install(cfg),
        setup=setup,
        caches=caches,
        timeout=15,
        variables=env or None,
        directory=cfg.directory,
    )
    template["before_script"] = template.pop("script")
    template.pop("timeout")
    return template


def render_renovate() -> str:
    config = {
        "$schema": "https://docs.renovatebot.com/renovate-schema.json",
        "extends": ["config:recommended"],
        # quoll regenerates .gitlab-ci.yml from quoll.toml: bump the versions there.
        "gitlabci": {"enabled": False},
    }
    return json.dumps(config, indent=2) + "\n"


def plan(project_dir: Path, target: Union[CIConfig, Repo]) -> List[PlannedFile]:
    repo = target if isinstance(target, Repo) else Repo.single(target)
    files = [
        planned(project_dir, PIPELINE_PATH, render_root(repo)),
        planned(project_dir, Path(JOBS_PATH), render_pipeline(repo)),
    ]
    # Renovate config is often customised by hand: only create it, never overwrite it.
    if repo.dependency_updates and not any((project_dir / name).exists() for name in RENOVATE_CONFIGS):
        files.append(planned(project_dir, RENOVATE_PATH, render_renovate(), create_only=True))
    return files


def _test_artifacts(cfg: CIConfig) -> Dict[str, Any]:
    """Test results and coverage for the merge request widgets; the report Codecov uploads."""
    ci = cfg.language.ci
    artifacts: Dict[str, Any] = {}
    reports: Dict[str, Any] = {}
    if cfg.test.reports:
        found = ci.reports(cfg)
        if found.junit:
            reports["junit"] = cfg.path(found.junit)
        if found.cobertura:
            reports["coverage_report"] = {"coverage_format": "cobertura", "path": cfg.path(found.cobertura)}
    if cfg.test.coverage and cfg.test.codecov:
        artifacts["paths"] = [cfg.path(ci.coverage_file(cfg))]
    if reports:
        artifacts["reports"] = reports
    if artifacts:
        artifacts = {"when": "always", **artifacts, "expire_in": "1 week"}
    return artifacts


def _skip_on_schedule(j: Dict[str, Any]) -> Dict[str, Any]:
    rules = [{"if": SCHEDULED, "when": "never"}, *j.get("rules", [{"when": "on_success"}])]
    rest = {k: v for k, v in j.items() if k not in ("stage", "image", "rules")}
    return {"stage": j["stage"], "image": j["image"], "rules": rules, **rest}


def _tool_job(image: str, items: List[Item], **options: Any) -> Dict[str, Any]:
    """A job running in a tool's image, whose entrypoint is the tool itself."""
    j = job("test", image, items, **options)
    j["image"] = {"name": image, "entrypoint": [""]}
    return j


def _services(cfg: CIConfig) -> List[Dict[str, Any]]:
    services = []
    for name in cfg.services:
        service = SERVICES[name]
        entry: Dict[str, Any] = {"name": service.image, "alias": name}
        if service.env:
            entry["variables"] = service.env
        services.append(entry)
    return services


def _export_step(env: Dict[str, str]) -> Step:
    # Services are reachable under their alias.
    return step("Point the app at the services", run="\n".join(f'export {k}="{v}"' for k, v in env.items()))


def _codecov_step(coverage_file: str) -> Item:
    command = 'codecovcli upload-process --fail-on-error --token "$CODECOV_TOKEN"'
    # The CLI takes files, not globs: let it search for the report instead.
    if "*" not in coverage_file:
        command += f" --file {coverage_file}"
    return step("Upload coverage to Codecov", run=f"pip install --quiet codecov-cli\n{command}")


def _sonar_command(cfg: CIConfig) -> str:
    command = f"sonar-scanner -Dsonar.organization={cfg.security.sonar_organization}"
    if cfg.security.sonar_project_key:
        command += f" -Dsonar.projectKey={cfg.security.sonar_project_key}"
    if cfg.directory != ".":
        command += f" -Dsonar.projectBaseDir={cfg.directory}"
    return command
