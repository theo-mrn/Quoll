"""Language-independent workflow generation, quoll.toml and planned files.

Per-language steps are tested in tests/languages/.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from quoll.ci.config import ConfigError, load_config, save_config
from quoll.ci.detect import default_config, detect
from quoll.files import MARKER
from quoll.platforms.github import ci as render
from tests.helpers import actionlint, config, load, steps, uses
from tests.samples import ALL_PROJECTS, GO, NODE_PNPM, PYTHON_PIP, PYTHON_UV


@pytest.mark.parametrize("name", list(ALL_PROJECTS))
def test_default_workflow_is_valid(make_project, tmp_path, name) -> None:
    text = render.render_workflow(config(make_project, ALL_PROJECTS[name]))
    doc = load(text)
    assert text.startswith(MARKER)
    assert doc["permissions"] == {"contents": "read"}
    assert doc["concurrency"]["cancel-in-progress"]
    for job in doc["jobs"].values():
        assert job["timeout-minutes"] > 0
    gate = doc["jobs"]["ci-result"]
    assert gate["name"] == render.GATE_CHECK
    assert gate["needs"] == [j for j in doc["jobs"] if j != "ci-result"]
    actionlint(tmp_path, text)


def test_render_is_deterministic(make_project) -> None:
    cfg = config(make_project, PYTHON_UV)
    assert render.render_workflow(cfg) == render.render_workflow(cfg)


def test_test_env_secrets(make_project) -> None:
    cfg = config(make_project, PYTHON_UV, test__env_secrets=["DATABASE_URL"])
    doc = load(render.render_workflow(cfg))
    step = next(s for s in steps(doc, "test") if s.get("name", "").startswith("Tests"))
    assert step["env"] == {"DATABASE_URL": "${{ secrets.DATABASE_URL }}"}


def test_optional_jobs(make_project, tmp_path) -> None:
    cfg = config(make_project, PYTHON_UV)
    cfg.test.codecov = True
    cfg.security.sonar = True
    cfg.security.sonar_organization = "acme"
    cfg.security.sonar_project_key = "acme_app"
    cfg.build.docker = True
    text = render.render_workflow(cfg)
    doc = load(text)
    assert "codecov/codecov-action@v7" in uses(doc, "test")
    sonar = doc["jobs"]["sonar"]
    assert "head.repo.full_name == github.repository" in sonar["if"]
    assert sonar["steps"][0]["with"]["fetch-depth"] == 0
    assert sonar["steps"][1]["with"]["args"] == "-Dsonar.projectKey=acme_app -Dsonar.organization=acme"
    assert "docker/build-push-action@v7" in uses(doc, "docker")
    assert {"sonar", "docker"} <= set(doc["jobs"]["ci-result"]["needs"])
    actionlint(tmp_path, text)


def test_disabled_jobs_are_omitted(make_project) -> None:
    cfg = config(make_project, GO)
    cfg.lint.enabled = cfg.build.enabled = cfg.build.docker = cfg.security.sast = False
    cfg.security.sbom = cfg.security.licenses = False
    doc = load(render.render_workflow(cfg))
    assert set(doc["jobs"]) == {"test", "audit", "secrets", "ci-result"}


def test_all_jobs_disabled_is_an_error(make_project) -> None:
    cfg = config(make_project, GO)
    cfg.lint.enabled = cfg.test.enabled = cfg.security.audit = cfg.build.enabled = False
    cfg.security.secrets = cfg.security.sast = cfg.build.docker = False
    cfg.security.sbom = cfg.security.licenses = False
    with pytest.raises(ValueError, match="disabled"):
        render.render_workflow(cfg)


# --------------------------------------------------------------------------- config


def test_config_roundtrip_preserves_other_sections(make_project) -> None:
    root = make_project(GO)
    (root / "quoll.toml").write_text('[cd]\ntarget = "ssh"\n')
    cfg = default_config(detect(root))
    save_config(root, cfg)
    assert load_config(root) == cfg
    assert '[cd]\ntarget = "ssh"' in (root / "quoll.toml").read_text()


def test_config_validation_errors(make_project) -> None:
    root = make_project(GO)
    save_config(root, default_config(detect(root)))
    text = (root / "quoll.toml").read_text().replace('"golangci-lint"', '"eslint"')
    (root / "quoll.toml").write_text(text)
    with pytest.raises(ConfigError, match="unknown lint tool 'eslint' for go"):
        load_config(root)


def test_config_rejects_unknown_keys(make_project) -> None:
    root = make_project(GO)
    save_config(root, default_config(detect(root)))
    (root / "quoll.toml").write_text((root / "quoll.toml").read_text() + "\n[ci.typo]\nx = 1\n")
    with pytest.raises(ConfigError, match="ci.typo"):
        load_config(root)


def test_missing_config() -> None:
    with pytest.raises(ConfigError, match="quoll ci init"):
        load_config(Path("/nonexistent"))


def test_sonar_requires_organization(make_project) -> None:
    with pytest.raises(ValueError, match="sonar_organization"):
        config(make_project, GO, security={"sonar": True})


# --------------------------------------------------------------------------- files


@pytest.mark.parametrize(
    "files, ecosystem",
    [(PYTHON_UV, "uv"), (PYTHON_PIP, "pip"), (NODE_PNPM, "npm"), (GO, "gomod")],
)
def test_dependabot_ecosystem(make_project, files, ecosystem) -> None:
    doc = yaml.safe_load(render.render_dependabot(config(make_project, files)))
    assert [u["package-ecosystem"] for u in doc["updates"]] == [ecosystem, "github-actions"]


def test_plan_never_overwrites_dependabot(make_project) -> None:
    root = make_project({**GO, ".github/dependabot.yml": "custom"})
    files = render.plan(root, default_config(detect(root)))
    assert [str(f.path) for f in files] == [".github/workflows/ci.yml", ".github/actions/quoll-setup/action.yml"]


def test_plan_detects_hand_written_workflow(make_project) -> None:
    root = make_project({**GO, ".github/workflows/ci.yml": "name: CI\n"})
    workflow = render.plan(root, default_config(detect(root)))[0]
    assert workflow.changed and not workflow.managed
    assert workflow.diff().startswith("--- a/.github/workflows/ci.yml")


@pytest.mark.parametrize("name", list(ALL_PROJECTS))
def test_no_expression_in_scripts(make_project, name) -> None:
    """No ${{ }} pasted into a script (Semgrep's run-shell-injection): values go through the environment."""
    import re

    from quoll.platforms.github.ci import render_setup_action

    cfg = config(make_project, ALL_PROJECTS[name])
    cfg.build.docker = True
    for text in (render.render_workflow(cfg), render_setup_action(cfg)):
        doc = yaml.safe_load(text)
        steps = [s for job in (doc.get("jobs") or {}).values() for s in job.get("steps", [])]
        steps += (doc.get("runs") or {}).get("steps", [])
        for step in steps:
            assert not re.search(r"\$\{\{", step.get("run") or ""), step["run"]


def test_dependabot_leaves_runtime_majors_to_quoll(make_project) -> None:
    """A base image's major is quoll.toml's ([docker] version), and Node's types follow the runtime's."""
    cfg = config(make_project, NODE_PNPM)
    doc = yaml.safe_load(render.render_dependabot(cfg, ["."]))
    npm, docker = (next(u for u in doc["updates"] if u["package-ecosystem"] == e) for e in ("npm", "docker"))
    major = ["version-update:semver-major"]
    assert npm["ignore"] == [{"dependency-name": "@types/node", "update-types": major}]
    assert docker["ignore"] == [{"dependency-name": "*", "update-types": major}]
