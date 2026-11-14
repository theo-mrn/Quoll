"""GitLab CI rendering: the same neutral steps as GitHub, run in the language's image."""
from __future__ import annotations

import pytest
import yaml

from quoll.ci.detect import default_config, detect
from quoll.platforms.gitlab.ci import RENOVATE_PATH, plan, render_pipeline, render_root
from tests.helpers import config, gitlab_lint, pipeline, script
from tests.samples import (
    ALL_PROJECTS,
    GO,
    JAVA_MAVEN,
    NEXTJS,
    NODE_PNPM,
    PHP_COMPOSER,
    PYTHON_POETRY,
    PYTHON_UV,
    RAILS,
    RUST,
)


@pytest.mark.parametrize("name", list(ALL_PROJECTS))
def test_default_pipeline_is_valid(make_project, tmp_path, name) -> None:
    text = render_pipeline(config(make_project, ALL_PROJECTS[name], platform="gitlab"))
    gitlab_lint(tmp_path, text)


@pytest.mark.parametrize("name", list(ALL_PROJECTS))
def test_full_pipeline_is_valid(make_project, tmp_path, name) -> None:
    cfg = config(
        make_project,
        ALL_PROJECTS[name],
        platform="gitlab",
        services=["postgres", "redis"],
        test__codecov=True,
        security__sonar=True,
        security__sonar_organization="acme",
        build__docker=True,
    )
    gitlab_lint(tmp_path, render_pipeline(cfg))


def test_workflow_rules_and_stages(make_project) -> None:
    doc = yaml.safe_load(render_root(config(make_project, GO, platform="gitlab", branches=["main", "release/*"])))
    assert doc["workflow"]["rules"] == [
        {"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'},
        {"if": '$CI_COMMIT_BRANCH == "main"'},
        {"if": "$CI_COMMIT_BRANCH =~ /^release\\/[^\\/]*$/"},
        {"if": "$CI_COMMIT_TAG"},
        {"if": '$CI_PIPELINE_SOURCE == "web"'},
        {"if": '$CI_PIPELINE_SOURCE == "schedule"'},
    ]
    assert doc["stages"] == ["test", "publish", "deploy"]
    # Infrastructure failures run again; a failing test doesn't.
    assert doc["default"]["retry"]["max"] == 2 and "script_failure" not in doc["default"]["retry"]["when"]
    # quoll's jobs first; quoll cd's pipeline and the project's own file (last: it overrides) when they exist.
    assert doc["include"] == [
        {"local": ".gitlab/quoll-ci.yml"},
        {"local": ".gitlab/cd.yml", "rules": [{"exists": [".gitlab/cd.yml"]}]},
        {"local": ".gitlab/custom-ci.yml", "rules": [{"exists": [".gitlab/custom-ci.yml"]}]},
    ]
    jobs = pipeline(make_project, GO)
    assert jobs["default"] == {"interruptible": True}
    assert {jobs[job]["stage"] for job in ("lint", "test", "audit")} == {"test"}


def test_versions_pick_the_image_and_matrix(make_project) -> None:
    doc = pipeline(make_project, PYTHON_UV, versions=["3.12", "3.13"])
    assert doc["lint"]["image"] == "ghcr.io/astral-sh/uv:python3.13-trixie"
    assert doc["test"]["image"] == "$IMAGE"
    assert doc["test"]["parallel"] == {
        "matrix": [
            {"PYTHON_VERSION": "3.12", "IMAGE": "ghcr.io/astral-sh/uv:python3.12-trixie"},
            {"PYTHON_VERSION": "3.13", "IMAGE": "ghcr.io/astral-sh/uv:python3.13-trixie"},
        ]
    }


def test_matrix_resolves_version_aliases(make_project) -> None:
    doc = pipeline(make_project, RUST, versions=["1.80", "stable"])
    images = [entry["IMAGE"] for entry in doc["test"]["parallel"]["matrix"]]
    assert images == ["rust:1.80", "rust:1"]


def test_github_only_steps_are_dropped_or_replaced(make_project) -> None:
    doc = pipeline(make_project, GO)
    # golangci-lint runs its GitHub Action on GitHub, its CLI here.
    assert "golangci-lint.run/install.sh" in script(doc, "lint")
    assert "govulncheck@latest ./..." in script(doc, "audit")
    assert "GITHUB_STEP_SUMMARY:-/dev/null" in script(doc, "test")
    for job in ("lint", "test", "audit"):
        assert "uses" not in str(doc[job])


def test_summary_steps_are_dropped(make_project) -> None:
    doc = pipeline(make_project, {**PYTHON_UV, "manage.py": "", "requirements.txt": "django\n"})
    assert "--format=markdown" not in str(doc)


def test_annotation_formats_are_github_only(make_project) -> None:
    assert "--output-format=github" not in script(pipeline(make_project, PYTHON_UV), "lint")
    assert "--format github" not in script(pipeline(make_project, RAILS), "lint")


def test_services_are_exported_not_job_variables(make_project) -> None:
    doc = pipeline(make_project, PYTHON_UV, services=["postgres", "redis"])
    test = doc["test"]
    assert test["services"][0] == {
        "name": "postgres:17-alpine",
        "alias": "postgres",
        "variables": {"POSTGRES_USER": "app", "POSTGRES_PASSWORD": "app", "POSTGRES_DB": "app"},
    }
    # Project CI/CD variables override job variables: an exported value can't be shadowed by a real database URL.
    first = test["script"][0]
    assert 'export DATABASE_URL="postgresql://app:app@postgres:5432/app"' in first
    assert 'export REDIS_URL="redis://redis:6379"' in first
    assert "DATABASE_URL" not in test.get("variables", {})


def test_caches_stay_in_the_project(make_project) -> None:
    doc = pipeline(make_project, GO)
    assert doc["lint"]["variables"]["GOMODCACHE"] == "$CI_PROJECT_DIR/.go/mod"
    assert doc["lint"]["cache"] == [
        {"key": {"files": ["go.sum"], "prefix": "go-$CI_JOB_NAME_SLUG"}, "paths": [".go/mod", ".go/build"]}
    ]
    assert pipeline(make_project, GO, cache=False)["lint"].get("cache") is None


@pytest.mark.parametrize(
    "files, image, setup",
    [
        (PYTHON_POETRY, "python:", "pip install poetry"),
        (NODE_PNPM, "node:", "corepack enable"),
        # Node.js 25+ images have no Yarn 1 any more.
        ({"package.json": {"name": "app", "scripts": {"test": "node --test"}}, "yarn.lock": "# yarn lockfile v1\n"},
         "node:", "npm install --global yarn@1"),
        (RUST, "rust:1", "rustup component add rustfmt clippy"),
        (PHP_COMPOSER, "php:", "install-php-extensions @composer"),
        (JAVA_MAVEN, "eclipse-temurin:", None),
    ],
)
def test_image_and_setup(make_project, files, image, setup) -> None:
    doc = pipeline(make_project, files)
    job = "lint" if "lint" in doc else "test"
    assert doc[job]["image"].startswith(image)
    if setup:
        assert setup in doc[job]["script"][0]


def test_framework_cache_and_env(make_project) -> None:
    doc = pipeline(make_project, NEXTJS, build__enabled=True, build__command="npm run build")
    assert doc["variables"] == {"NEXT_TELEMETRY_DISABLED": "1"}
    keys = [c["key"]["prefix"] for c in doc["build"]["cache"]]
    assert keys == ["node-$CI_JOB_NAME_SLUG", "nextjs-$CI_JOB_NAME_SLUG"]


def test_codecov_and_sonar_jobs(make_project) -> None:
    doc = pipeline(
        make_project, PYTHON_UV, test__codecov=True, security__sonar=True, security__sonar_organization="acme"
    )
    assert doc["test"]["artifacts"]["paths"] == ["coverage.xml"]
    assert doc["codecov"]["needs"] == [{"job": "test", "artifacts": True}]
    assert "--file coverage.xml" in script(doc, "codecov")
    never = {"if": '$CI_PIPELINE_SOURCE == "schedule"', "when": "never"}
    assert doc["sonar"]["rules"] == [never, {"if": "$SONAR_TOKEN"}]
    assert doc["sonar"]["variables"]["GIT_DEPTH"] == "0"


def test_go_oldstable_has_no_image(make_project) -> None:
    with pytest.raises(ValueError, match="oldstable"):
        pipeline(make_project, GO, versions=["oldstable", "stable"])


def test_renovate_is_created_once(make_project) -> None:
    root = make_project(GO)
    det = detect(root)
    det.platform = "gitlab"
    cfg = default_config(det)
    assert [str(f.path) for f in plan(root, cfg)] == [".gitlab-ci.yml", ".gitlab/quoll-ci.yml", str(RENOVATE_PATH)]
    (root / "renovate.json5").write_text("{}")
    assert [str(f.path) for f in plan(root, cfg)] == [".gitlab-ci.yml", ".gitlab/quoll-ci.yml"]
