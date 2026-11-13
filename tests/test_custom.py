"""The project's own steps and jobs ([[ci.steps]], [[ci.jobs]]) and the scheduled security scans ([ci.schedule])."""
from __future__ import annotations

import json
import subprocess

import httpx
import pytest
import respx
import yaml
from typer.testing import CliRunner

from quoll.ci.config import load_config
from quoll.main import app
from quoll.platforms.github import ci as github
from quoll.platforms.gitlab.api import GitLabAPI
from quoll.platforms.gitlab.ci import render_pipeline
from tests.helpers import actionlint, config, gitlab_lint, load
from tests.samples import GO, PYTHON_UV

STEPS = [
    {"job": "test", "name": "Migrate", "run": "uv run alembic upgrade head", "secrets": ["DB_KEY"]},
    {"job": "lint", "when": "after", "name": "Docs", "run": "uv run mkdocs build --strict"},
]


def _names(steps) -> list:
    return [s.get("name") for s in steps]


# --------------------------------------------------------------------------- [[ci.steps]]


def test_github_custom_steps(make_project, tmp_path) -> None:
    action = {"job": "test", "when": "after", "name": "Upload report", "uses": "actions/upload-artifact@v7",
              "with": {"name": "report", "path": "report.html"}}
    cfg = config(make_project, PYTHON_UV, steps=[*STEPS, action])
    text = github.render_workflow(cfg)
    doc = load(text)
    test = _names(doc["jobs"]["test"]["steps"])
    # Right after the dependencies, before the tests.
    assert test.index("Install dependencies") + 1 == test.index("Migrate") < test.index("Tests with coverage")
    migrate = doc["jobs"]["test"]["steps"][test.index("Migrate")]
    assert migrate["env"] == {"DB_KEY": "${{ secrets.DB_KEY }}"}
    upload = doc["jobs"]["test"]["steps"][test.index("Upload report")]
    assert upload["uses"] == "actions/upload-artifact@v7" and upload["with"]["path"] == "report.html"
    assert _names(doc["jobs"]["lint"]["steps"])[-1] == "Docs"
    actionlint(tmp_path, text)


def test_gitlab_custom_steps(make_project, tmp_path) -> None:
    text = render_pipeline(config(make_project, PYTHON_UV, platform="gitlab", steps=STEPS))
    doc = yaml.safe_load(text)
    script = doc["test"]["script"]
    assert script.index("uv sync --locked --all-extras") + 1 == script.index("uv run alembic upgrade head")
    assert doc["lint"]["script"][-1] == "uv run mkdocs build --strict"
    gitlab_lint(tmp_path, text)


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"steps": [{"job": "deploy", "name": "x", "run": "x"}]}, "unknown job 'deploy'"),
        ({"steps": [{"job": "test", "when": "during", "name": "x", "run": "x"}]}, "before' or 'after"),
        ({"steps": [{"job": "test", "name": "x"}]}, "either run or uses"),
        ({"steps": [{"job": "test", "name": "x", "run": "y", "with": {"a": 1}}]}, "with only goes with uses"),
        ({"platform": "gitlab", "steps": [{"job": "test", "name": "x", "uses": "a/b@v1"}]}, "custom-ci.yml"),
        ({"schedule": {"cron": "weekly"}}, "5 fields"),
    ],
)
def test_validation(make_project, overrides, error) -> None:
    platform = overrides.pop("platform", "github")
    with pytest.raises(ValueError, match=error):
        config(make_project, GO, platform=platform, **overrides)


def test_custom_steps_survive_update(make_project) -> None:
    root = make_project(GO)
    runner = CliRunner()
    assert runner.invoke(app, ["ci", "init", "-y", "-d", str(root)]).exit_code == 0
    with open(root / "quoll.toml", "a") as f:
        f.write('\n[[ci.steps]]\njob = "test"\nname = "Generate"\nrun = "go generate ./..."\n')
    assert runner.invoke(app, ["ci", "check", "-d", str(root)]).exit_code == 1
    assert runner.invoke(app, ["ci", "update", "-y", "-d", str(root)]).exit_code == 0
    assert runner.invoke(app, ["ci", "check", "-d", str(root)]).exit_code == 0
    assert "go generate ./..." in (root / ".github/workflows/ci.yml").read_text()
    assert load_config(root).steps[0].name == "Generate"


# --------------------------------------------------------------------------- building blocks for your own CI


def test_github_setup_action(make_project, tmp_path) -> None:
    root = make_project(PYTHON_UV)
    assert CliRunner().invoke(app, ["ci", "init", "-y", "-d", str(root)]).exit_code == 0
    action = yaml.safe_load((root / ".github/actions/quoll-setup/action.yml").read_text())
    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["version"]["default"] == "3.14"
    steps = action["runs"]["steps"]
    assert steps[0]["uses"].startswith("astral-sh/setup-uv@")
    assert steps[0]["with"]["python-version"] == "${{ inputs.version }}"
    assert steps[1] == {"name": "Install dependencies", "run": "uv sync --locked --all-extras", "shell": "bash"}
    # A workflow of your own using it, as actionlint sees it.
    workflow = root / ".github/workflows/e2e.yml"
    workflow.write_text(
        "on: push\njobs:\n  e2e:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n"
        "      - uses: ./.github/actions/quoll-setup\n        with:\n          version: '3.13'\n"
        "      - run: uv run pytest e2e\n"
    )
    actionlint(tmp_path, workflow.read_text())
    # `quoll ci check` covers the action too.
    (root / ".github/actions/quoll-setup/action.yml").write_text("# Generated by quoll\nname: changed\n")
    assert CliRunner().invoke(app, ["ci", "check", "-d", str(root)]).exit_code == 1


def test_gitlab_setup_template_and_layout(make_project, tmp_path) -> None:
    root = make_project(PYTHON_UV)
    assert CliRunner().invoke(app, ["ci", "init", "-y", "--platform", "gitlab", "-d", str(root)]).exit_code == 0
    jobs = yaml.safe_load((root / ".gitlab/quoll-ci.yml").read_text())
    template = jobs[".quoll-setup"]
    assert template["image"] == "ghcr.io/astral-sh/uv:python3.14-bookworm"
    assert template["before_script"] == ["uv sync --locked --all-extras"]
    assert template["cache"][0]["paths"] == [".venv"]
    root_file = (root / ".gitlab-ci.yml").read_text()
    assert root_file.index("quoll-ci.yml") < root_file.index("custom-ci.yml")
    gitlab_lint(tmp_path, root_file)
    gitlab_lint(tmp_path, (root / ".gitlab/quoll-ci.yml").read_text(), "quoll-ci.yml")


# --------------------------------------------------------------------------- eject


@pytest.mark.parametrize("platform, files", [
    ("github", [".github/workflows/ci.yml", ".github/actions/quoll-setup/action.yml"]),
    ("gitlab", [".gitlab-ci.yml", ".gitlab/quoll-ci.yml"]),
])
def test_eject(make_project, platform, files) -> None:
    root = make_project(GO)
    runner = CliRunner()
    assert runner.invoke(app, ["ci", "init", "-y", "--platform", platform, "-d", str(root)]).exit_code == 0
    before = {f: (root / f).read_text() for f in files}
    result = runner.invoke(app, ["ci", "eject", "-y", "-d", str(root)])
    assert result.exit_code == 0, result.output
    for f in files:
        text = (root / f).read_text()
        assert text.startswith("# Maintained by hand") and "Generated by quoll" not in text
        # Same pipeline, minus quoll's header.
        assert text.splitlines()[1:] == before[f].splitlines()[2:]
    toml = (root / "quoll.toml").read_text()
    assert "[ci]" not in toml and "[project]" in toml
    assert "quoll ci init" in runner.invoke(app, ["ci", "check", "-d", str(root)]).output


# --------------------------------------------------------------------------- scheduled security scans


def test_github_schedule_runs_only_security_jobs(make_project) -> None:
    cfg = config(make_project, GO, security={"sonar": True, "sonar_organization": "acme"})
    doc = load(github.render_workflow(cfg))
    assert doc["on"]["schedule"] == [{"cron": "0 6 * * 1"}]
    jobs = doc["jobs"]
    for name in ("lint", "test", "build"):
        assert jobs[name]["if"] == "${{ github.event_name != 'schedule' }}"
    for name in ("audit", "secrets", "sast", "sbom", "docker"):
        assert "if" not in jobs[name]
    assert jobs["sonar"]["if"].startswith("${{ github.event_name != 'schedule' && (github.event_name")


def test_gitlab_schedule_runs_only_security_jobs(make_project) -> None:
    doc = yaml.safe_load(render_pipeline(config(make_project, GO, platform="gitlab")))
    never = {"if": '$CI_PIPELINE_SOURCE == "schedule"', "when": "never"}
    for name in ("lint", "test", "build"):
        assert doc[name]["rules"] == [never, {"when": "on_success"}]
    for name in ("audit", "secrets", "sast", "sbom", "docker"):
        assert "rules" not in doc[name]


def test_schedule_off(make_project) -> None:
    doc = load(github.render_workflow(config(make_project, GO, schedule={"enabled": False})))
    assert "schedule" not in doc["on"] and "if" not in doc["jobs"]["lint"]


@respx.mock
def test_gitlab_api_creates_then_updates_the_schedule(monkeypatch) -> None:
    import quoll.config.settings as settings

    monkeypatch.setattr(settings.settings, "gitlab_token", "token")
    schedules = "https://gitlab.com/api/v4/projects/acme%2Fapi/pipeline_schedules"
    listing = respx.get(schedules).mock(return_value=httpx.Response(200, json=[]))
    create = respx.post(schedules).mock(return_value=httpx.Response(201, json={}))
    assert GitLabAPI().ensure_schedule("acme/api", "main", "0 6 * * 1")
    assert json.loads(create.calls[0].request.content)["cron"] == "0 6 * * 1"

    listing.mock(return_value=httpx.Response(200, json=[{"id": 7, "description": "quoll: security scans"}]))
    update = respx.put(f"{schedules}/7").mock(return_value=httpx.Response(200, json={}))
    GitLabAPI().ensure_schedule("acme/api", "main", "0 3 * * *")
    assert json.loads(update.calls[0].request.content)["cron"] == "0 3 * * *"


def test_schedule_command(make_project, monkeypatch) -> None:
    from quoll import platforms
    from quoll.config.settings import settings

    root = make_project(GO)
    runner = CliRunner()
    assert runner.invoke(app, ["ci", "init", "-y", "-d", str(root)]).exit_code == 0
    assert "in the pipeline itself" in runner.invoke(app, ["ci", "schedule", "-d", str(root)]).output

    root = make_project({**GO, "quoll.toml": ""})
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@gitlab.com:acme/api.git"], cwd=root, check=True)
    assert runner.invoke(app, ["ci", "init", "-y", "--force", "-d", str(root)]).exit_code == 0
    monkeypatch.setattr(settings, "gitlab_token", "token")
    calls = []

    class FakeAPI:
        def ensure_schedule(self, repo, branch, cron):
            calls.append((repo, branch, cron))
            return True

    monkeypatch.setattr(platforms.get("gitlab"), "api", lambda host=None: FakeAPI())
    result = runner.invoke(app, ["ci", "schedule", "-d", str(root)])
    assert result.exit_code == 0, result.output
    assert calls == [("acme/api", "main", "0 6 * * 1")]


def test_add_step_command(make_project, tmp_path) -> None:
    """`quoll ci add-step`: the step in quoll.toml and the pipeline, without writing TOML."""
    root = make_project(GO)
    assert CliRunner().invoke(app, ["ci", "init", "-y", "-d", str(root)]).exit_code == 0
    result = CliRunner().invoke(app, [
        "ci", "add-step", "-d", str(root), "--job", "test", "--when", "after", "--name", "Integration",
        "--run", "go test -tags=integration ./...", "--secret", "API_KEY",
    ])
    assert result.exit_code == 0, result.output
    assert '[[ci.steps]]\njob = "test"\nwhen = "after"\nname = "Integration"' in (root / "quoll.toml").read_text()
    steps = load((root / ".github/workflows/ci.yml").read_text())["jobs"]["test"]["steps"]
    step = next(s for s in steps if s.get("name") == "Integration")
    assert step["env"] == {"API_KEY": "${{ secrets.API_KEY }}"}
    assert CliRunner().invoke(app, ["ci", "check", "-d", str(root)]).exit_code == 0
    actionlint(tmp_path, (root / ".github/workflows/ci.yml").read_text())

    # An action, with its inputs.
    result = CliRunner().invoke(app, [
        "ci", "add-step", "-d", str(root), "--job", "build", "--when", "after", "--name", "Upload",
        "--uses", "acme/upload@v2", "--with", "path=bin/",
    ])
    assert result.exit_code == 0, result.output
    assert load_config(root).steps[-1].with_ == {"path": "bin/"}


@pytest.mark.parametrize("args, error", [
    (["--job", "deploy", "--when", "after", "--name", "X", "--run", "x"], "unknown job 'deploy'"),
    (["--job", "test", "--when", "after", "--name", "X", "--uses", "acme/x@v1"], "actions (--uses) are GitHub's"),
])
def test_add_step_errors(make_project, args, error) -> None:
    root = make_project(GO)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    assert CliRunner().invoke(app, ["ci", "init", "-y", "--platform", "gitlab", "-d", str(root)]).exit_code == 0
    result = CliRunner().invoke(app, ["ci", "add-step", "-d", str(root), *args])
    assert result.exit_code == 1 and error in result.output
