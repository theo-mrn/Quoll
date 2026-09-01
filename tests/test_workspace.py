"""Monorepos: several projects (a front-end, a back-end...), each with its own quoll.toml, one pipeline."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from quoll.config.quoll_toml import ConfigError
from quoll.main import app
from quoll.workspace import discover, find_root, load_repo
from tests.helpers import actionlint, gitlab_lint, load
from tests.samples import FASTAPI, GO, NEXTJS, NODE_PNPM

runner = CliRunner()


def _forge(*args: str):
    return runner.invoke(app, list(args))


def _workspace(make_project, remote: str = "git@github.com:acme/shop.git") -> Path:
    files = {**{f"backend/{k}": v for k, v in FASTAPI.items()}, **{f"frontend/{k}": v for k, v in NEXTJS.items()}}
    files["docs/requirements.txt"] = "mkdocs\n"  # not a project
    root = make_project(files)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)
    return root


# --------------------------------------------------------------------------- discovery and configuration


def test_discover(make_project) -> None:
    files = {"apps/web/package.json": {"name": "web"}, "services/api/go.mod": "module api\n\ngo 1.25\n",
             "examples/demo/package.json": {"name": "demo"}, "docs/requirements.txt": "mkdocs\n", "README.md": ""}
    assert discover(make_project(files)) == ["apps/web", "services/api"]


def test_init_writes_the_workspace(make_project) -> None:
    root = _workspace(make_project)
    result = _forge("ci", "init", "-y", "-d", str(root))
    assert result.exit_code == 0, result.output
    assert "quoll.toml (workspace: backend, frontend)" in result.output
    toml = (root / "quoll.toml").read_text()
    assert 'members = [\n    "backend",\n    "frontend",\n]' in toml and "[ci.security]" in toml
    assert 'stack = "python"' in (root / "backend/quoll.toml").read_text()
    assert 'stack = "node"' in (root / "frontend/quoll.toml").read_text()
    # Generated at the repository root, checked from anywhere in it.
    assert (root / ".github/actions/quoll-setup-backend/action.yml").exists()
    assert _forge("ci", "check", "-d", str(root / "frontend")).exit_code == 0
    assert find_root(root / "backend") == root
    repo = load_repo(root)
    assert [(m.name, m.directory) for m in repo.members] == [("backend", "backend"), ("frontend", "frontend")]


def test_members_must_share_the_platform(make_project) -> None:
    root = _workspace(make_project)
    assert _forge("ci", "init", "-y", "-d", str(root)).exit_code == 0
    config = root / "frontend/quoll.toml"
    config.write_text(config.read_text().replace('platform = "github"', 'platform = "gitlab"'))
    with pytest.raises(ConfigError, match="same \\[project\\] platform"):
        load_repo(root)


# --------------------------------------------------------------------------- GitHub


def test_github_workflow(make_project, tmp_path) -> None:
    root = _workspace(make_project)
    assert _forge("ci", "init", "-y", "-d", str(root)).exit_code == 0
    text = (root / ".github/workflows/ci.yml").read_text()
    jobs = load(text)["jobs"]
    assert {"changes", "backend-test", "frontend-test", "frontend-build", "secrets", "sast", "ci-result"} <= set(jobs)
    # Scans of the whole repository run once.
    assert not any(name.endswith(("-secrets", "-sast")) for name in jobs)
    test = jobs["frontend-test"]
    assert test["name"] == "frontend: Test"
    assert test["needs"] == ["changes"]
    assert test["if"] == "${{ github.event_name != 'schedule' && (needs.changes.outputs.frontend == 'true') }}"
    assert test["defaults"] == {"run": {"working-directory": "frontend"}}
    assert test["env"] == {"NEXT_TELEMETRY_DISABLED": "1"}
    setup_node = next(s for s in test["steps"] if s.get("uses", "").startswith("actions/setup-node"))
    assert setup_node["with"]["cache-dependency-path"] == "frontend/package-lock.json"
    report = next(s for s in test["steps"] if s.get("name") == "Test report")
    assert report["with"]["report_paths"] == "frontend/junit.xml"
    # Security jobs of members still run on schedule (changes counts everything as changed then).
    assert jobs["backend-audit"]["if"] == "${{ needs.changes.outputs.backend == 'true' }}"
    assert jobs["changes"]["outputs"] == {
        "backend": "${{ steps.diff.outputs.backend }}",
        "frontend": "${{ steps.diff.outputs.frontend }}",
    }
    assert "env" not in load(text)  # framework settings are per job
    actionlint(tmp_path, text)

    action = yaml.safe_load((root / ".github/actions/quoll-setup-frontend/action.yml").read_text())
    assert all(s.get("working-directory") == "frontend" for s in action["runs"]["steps"] if "run" in s)
    dependabot = yaml.safe_load((root / ".github/dependabot.yml").read_text())
    assert [(u["package-ecosystem"], u["directory"]) for u in dependabot["updates"]] == [
        ("pip", "/backend"), ("npm", "/frontend"), ("github-actions", "/"),
    ]


def test_changes_detection(make_project) -> None:
    """The changes job's script, on a real history."""
    root = _workspace(make_project)
    assert _forge("ci", "init", "-y", "-d", str(root)).exit_code == 0
    script = load((root / ".github/workflows/ci.yml").read_text())["jobs"]["changes"]["steps"][1]["run"]

    def commit(path: str) -> str:
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
        (root / path).write_text((root / path).read_text() + "\n" if (root / path).exists() else "x\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        git = ["git", "-c", "user.name=q", "-c", "user.email=q@q"]
        subprocess.run([*git, "commit", "-qm", path], cwd=root, check=True)
        return base

    def changed(**env: str) -> str:
        out = root.parent / "out"
        out.write_text("")
        env = {"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(out), **env}
        subprocess.run(["bash", "-c", script], cwd=root, env=env, check=True, capture_output=True)
        return " ".join(out.read_text().split())

    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=q", "-c", "user.email=q@q", "commit", "-qm", "init"], cwd=root, check=True)
    base = commit("backend/app/__init__.py")
    assert changed(EVENT="push", PUSH_BEFORE=base) == "backend=true frontend=false"
    assert changed(EVENT="pull_request", PR_BASE=base) == "backend=true frontend=false"
    assert changed(EVENT="merge_group", QUEUE_BASE=base) == "backend=true frontend=false"
    base = commit("quoll.toml")
    assert changed(EVENT="push", PUSH_BEFORE=base) == "backend=true frontend=true"
    # New branch (no previous commit), schedule, manual run: everything.
    assert changed(EVENT="push", PUSH_BEFORE="0" * 40) == "backend=true frontend=true"
    assert changed(EVENT="schedule") == "backend=true frontend=true"


# --------------------------------------------------------------------------- GitLab


def test_gitlab_pipeline(make_project, tmp_path) -> None:
    root = _workspace(make_project, "git@gitlab.com:acme/shop.git")
    assert _forge("ci", "init", "-y", "-d", str(root)).exit_code == 0
    text = (root / ".gitlab/quoll-ci.yml").read_text()
    doc = yaml.safe_load(text)
    test = doc["frontend-test"]
    assert test["rules"] == [
        {"if": '$CI_PIPELINE_SOURCE == "schedule"', "when": "never"},
        {"when": "on_success",
         "changes": {"paths": ["frontend/**/*", "quoll.toml", ".gitlab-ci.yml", ".gitlab/**/*"]}},
    ]
    assert test["script"][0] == 'cd "frontend"'
    assert test["variables"]["npm_config_cache"] == "$CI_PROJECT_DIR/frontend/.npm"
    assert test["cache"][0]["key"]["files"] == ["frontend/package-lock.json"]
    assert test["artifacts"]["reports"]["junit"] == "frontend/junit.xml"
    assert test["variables"]["NEXT_TELEMETRY_DISABLED"] == "1" and "variables" not in doc
    # One template per project for your own jobs, running in its directory.
    assert doc[".quoll-setup-backend"]["before_script"][0] == 'cd "backend"'
    assert "secrets" in doc and "backend-secrets" not in doc
    gitlab_lint(tmp_path, text, "quoll-ci.yml")
    gitlab_lint(tmp_path, (root / ".gitlab-ci.yml").read_text())


# --------------------------------------------------------------------------- Docker and delivery


@pytest.mark.parametrize("remote, images, files", [
    ("git@github.com:Acme/Shop.git", ["ghcr.io/acme/shop-backend", "ghcr.io/acme/shop-frontend"],
     [".github/workflows/cd-backend.yml", ".github/workflows/cd-frontend.yml"]),
    (
        "git@gitlab.com:acme/shop.git",
        ["registry.gitlab.com/acme/shop/backend", "registry.gitlab.com/acme/shop/frontend"],
        [".gitlab/cd.yml"],
    ),
])
def test_docker_and_delivery(make_project, tmp_path, remote, images, files) -> None:
    root = _workspace(make_project, remote)
    assert _forge("ci", "init", "-y", "-d", str(root)).exit_code == 0
    result = _forge("docker", "init", "-y", "-d", str(root))
    assert result.exit_code == 0, result.output
    assert (root / "backend/Dockerfile").exists() and (root / "frontend/Dockerfile").exists()
    result = _forge("cd", "init", "-y", "-d", str(root))
    assert result.exit_code == 0, result.output
    assert [f for f in files if (root / f).exists()] == files
    for member, image in zip(("backend", "frontend"), images):
        assert f'image = "{image}"' in (root / member / "quoll.toml").read_text()
    assert _forge("cd", "check", "-d", str(root / "backend")).exit_code == 0
    assert _forge("docker", "check", "-d", str(root)).exit_code == 0
    if "github" in remote:
        workflow = load((root / files[0]).read_text())
        assert workflow["name"] == "CD (backend)"
        assert workflow["on"]["push"]["paths"] == ["backend/**", "quoll.toml", ".github/workflows/cd-backend.yml"]
        job = workflow["jobs"]["image"]
        assert job["defaults"] == {"run": {"working-directory": "backend"}}
        push = next(s for s in job["steps"] if s.get("name") == "Push image")
        assert push["with"]["context"] == "backend"
        attest = next(s for s in job["steps"] if s.get("name") == "Attest SBOM")
        assert attest["with"]["sbom-path"] == "backend/sbom.cdx.json"
        for f in files:
            actionlint(tmp_path, (root / f).read_text())
    else:
        cd = yaml.safe_load((root / files[0]).read_text())
        assert cd["backend-publish"]["script"][0] == 'cd "backend"'
        assert cd["backend-publish"]["resource_group"] == "publish-backend"
        assert cd["backend-publish"]["artifacts"]["paths"] == ["backend/sbom.cdx.json"]
        links = cd["release"]["release"]["assets"]["links"]
        assert [link["name"] for link in links] == ["backend SBOM (CycloneDX)", "frontend SBOM (CycloneDX)"]
        assert [n["job"] for n in cd["release"]["needs"]] == ["backend-publish", "frontend-publish"]
        gitlab_lint(tmp_path, (root / files[0]).read_text(), "cd.yml")


def test_eject_workspace(make_project) -> None:
    root = _workspace(make_project)
    assert _forge("ci", "init", "-y", "-d", str(root)).exit_code == 0
    assert _forge("ci", "eject", "-y", "-d", str(root)).exit_code == 0
    for config in ("quoll.toml", "backend/quoll.toml", "frontend/quoll.toml"):
        assert "[ci]" not in (root / config).read_text()
    assert "[workspace]" in (root / "quoll.toml").read_text()


def test_single_project_is_not_a_workspace(make_project) -> None:
    root = make_project(GO)
    assert _forge("ci", "init", "-y", "-d", str(root)).exit_code == 0
    assert "[workspace]" not in (root / "quoll.toml").read_text()
    assert "changes" not in load((root / ".github/workflows/ci.yml").read_text())["jobs"]


def test_workspace_compose() -> None:
    from quoll.docker.config import DockerConfig
    from quoll.docker.render import render_workspace_compose

    orders = DockerConfig(stack="python", framework="fastapi", package_manager="uv", version="3.13",
                          command="uvicorn main:app", services=["postgres", "redis"])
    accounts = DockerConfig(stack="node", package_manager="npm", version="24", command="node server.js",
                            services=["postgres"])
    doc = yaml.safe_load(render_workspace_compose(
        [("orders", "services/orders", orders), ("user-accounts", "services/user-accounts", accounts)]
    ))
    services = doc["services"]
    assert list(services) == ["orders", "user-accounts", "postgres", "postgres-databases", "redis"]
    assert services["orders"]["ports"] == ["8000:8000"] and services["user-accounts"]["ports"] == ["8001:8000"]
    # A database each, on the shared server, created when missing at every `up` (by a one-shot container).
    assert services["orders"]["environment"]["DATABASE_URL"].endswith("@postgres:5432/orders")
    assert services["user-accounts"]["environment"]["PGDATABASE"] == "user_accounts"
    script = doc["configs"]["postgres-databases"]["content"]
    assert "CREATE DATABASE orders" in script and "CREATE DATABASE user_accounts" in script
    create = services["postgres-databases"]
    assert create["image"] == services["postgres"]["image"]
    assert create["depends_on"] == {"postgres": {"condition": "service_healthy"}}
    assert "redis-databases" not in services
    # Each reaches the others by name.
    assert services["orders"]["environment"]["USER_ACCOUNTS_URL"] == "http://user-accounts:8000"
    assert services["user-accounts"]["environment"]["ORDERS_URL"] == "http://orders:8000"
    assert "REDIS_URL" not in services["user-accounts"]["environment"]
    assert services["user-accounts"]["depends_on"] == {
        "postgres": {"condition": "service_healthy"},
        "postgres-databases": {"condition": "service_completed_successfully"},
    }


@pytest.mark.parametrize("remote", ["git@github.com:acme/shop.git", "git@gitlab.com:acme/shop.git"])
def test_build_output_is_kept(make_project, remote) -> None:
    files = {**{f"web/{k}": v for k, v in NODE_PNPM.items()}, **{f"site/{k}": v for k, v in NEXTJS.items()}}
    root = make_project(files)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)
    assert _forge("ci", "init", "-y", "-d", str(root)).exit_code == 0
    assert 'artifacts = [\n    "dist/",\n]' in (root / "web/quoll.toml").read_text()
    assert "artifacts" not in (root / "site/quoll.toml").read_text()  # Next.js' .next/ isn't a deliverable
    if "github" in remote:
        jobs = load((root / ".github/workflows/ci.yml").read_text())["jobs"]
        keep = jobs["web-build"]["steps"][-1]
        assert keep["uses"].startswith("actions/upload-artifact@")
        assert keep["with"] == {"name": "web-build", "path": "web/dist/", "retention-days": 7}
        assert "upload-artifact" not in str(jobs["site-build"])
    else:
        jobs = yaml.safe_load((root / ".gitlab/quoll-ci.yml").read_text())
        assert jobs["web-build"]["artifacts"] == {"paths": ["web/dist/"], "expire_in": "1 week"}
        assert "artifacts" not in jobs["site-build"]
    assert _forge("ci", "check", "-d", str(root)).exit_code == 0
