"""`quoll new`: a project from nothing. Starters are replaced by fakes (no network); the real ones are run by
QUOLL_NEW_TESTS=run, below."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from quoll import languages
from quoll.languages.base import StarterOptions
from quoll.main import app
from quoll.starters import from_template

runner = CliRunner()
calls: list = []


def _fake(role: str, files: dict):
    def create(directory: Path, options: StarterOptions):
        calls.append((role, directory.name, options))
        for rel, content in files.items():
            path = directory / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(content) if isinstance(content, dict) else content)
        (directory / ".nvmrc").write_text(f"{options.runtime or '24'}\n")
        return ["an old version"] if options.version == "1" else []

    return create


FRONT = {
    "package.json": {"name": "web", "scripts": {"build": "vite build"}, "devDependencies": {"vite": "^7"}},
    "package-lock.json": "{}",
}
BACK = {
    "package.json": {"name": "api", "scripts": {"start": "node server.js", "test": "vitest run"},
                     "dependencies": {"express": "^5"}, "devDependencies": {"vitest": "^3"}},
    "package-lock.json": "{}",
    "server.js": "",
}


@pytest.fixture(autouse=True)
def fake_starters(monkeypatch):
    from quoll.languages.base import Starter

    calls.clear()
    fakes = [
        Starter("web", "Web", "front", _fake("front", FRONT), runtime="node", runtime_default="24"),
        Starter("api", "API", "back", _fake("back", BACK), runtime="node", runtime_default="24"),
    ]
    monkeypatch.setattr(languages, "starters", lambda role="": [s for s in fakes if not role or s.role == role])
    monkeypatch.setenv("GIT_AUTHOR_NAME", "quoll")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "quoll@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "quoll")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "quoll@example.com")


def _new(tmp_path, *args: str):
    return runner.invoke(app, ["new", "shop", "-d", str(tmp_path), "--local", "-y", *args])


def test_front_and_back(tmp_path) -> None:
    result = _new(tmp_path, "--front", "web@1", "--back", "api", "--node", "20", "--cd", "--k8s")
    assert result.exit_code == 0, result.output
    root = tmp_path / "shop"
    assert calls == [
        ("front", "front", StarterOptions("shop-front", "1", "20")),
        ("back", "back", StarterOptions("shop-back", "", "20")),
    ]
    # A workspace: one quoll.toml per project, one pipeline, an image and a delivery each.
    assert 'members = [\n    "back",\n    "front",\n]' in (root / "quoll.toml").read_text()
    for part in ("front", "back"):
        assert (root / part / "Dockerfile").exists() and "[cd]" in (root / part / "quoll.toml").read_text()
        # Node.js 20 everywhere: the CI reads .nvmrc, the image is built on it.
        config = (root / part / "quoll.toml").read_text()
        assert 'version_file = ".nvmrc"' in config and '[docker]\nversion = "20"' in config
    jobs = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())["jobs"]
    # Docker ran before the CI: the images are built and scanned there.
    assert {"front-docker", "back-docker", "back-test"} <= set(jobs)
    assert (root / ".github/workflows/cd-back.yml").exists()
    # Deployed to Kubernetes: a chart each, checked by the CI, deployed after publication.
    assert {"front-chart", "back-chart"} <= set(jobs)
    assert "deploy-staging" in yaml.safe_load((root / ".github/workflows/cd-back.yml").read_text())["jobs"]
    assert yaml.safe_load((root / "front/chart/values.yaml").read_text())["env"] == {"BACK_URL": "http://back:3000"}
    assert "front/" in (root / "README.md").read_text()
    # The front-end calls the API on its own origin: nginx forwards /api/ to BACK_URL, which compose.yaml sets.
    assert '[docker.proxy]\n"/api/" = "BACK_URL"' in (root / "front/quoll.toml").read_text()
    assert "location /api/ {\n        proxy_pass ${BACK_URL};" in (root / "front/Dockerfile").read_text()
    front = yaml.safe_load((root / "compose.yaml").read_text())["services"]["front"]
    assert front["environment"]["BACK_URL"] == "http://back:3000"
    assert front["depends_on"] == {"back": {"condition": "service_started"}}
    log = subprocess.run(["git", "log", "--oneline"], cwd=root, capture_output=True, text=True).stdout
    assert "chore: create shop with quoll" in log
    assert "an old version" in result.output  # the starter's warning


def test_single_part_is_the_repository(tmp_path) -> None:
    result = _new(tmp_path, "--front", "none", "--back", "api", "--platform", "gitlab")
    assert result.exit_code == 0, result.output
    root = tmp_path / "shop"
    assert (root / "server.js").exists() and not (root / "back").exists()
    assert "[workspace]" not in (root / "quoll.toml").read_text()
    assert (root / ".gitlab/quoll-ci.yml").exists()


@pytest.mark.parametrize("args, error", [
    (["--front", "vue", "--back", "api"], "unknown front-end 'vue'"),
    (["--front", "none", "--back", "none"], "nothing to create"),
    (["--platform", "bitbucket"], "unknown platform"),
])
def test_errors(tmp_path, args, error) -> None:
    result = _new(tmp_path, *args)
    assert result.exit_code == 1 and error in result.output


def test_refuses_a_non_empty_directory(tmp_path) -> None:
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "notes.txt").write_text("mine")
    result = _new(tmp_path, "--front", "web", "--back", "none")
    assert result.exit_code == 1 and "isn't empty" in result.output


def test_express_template(tmp_path) -> None:
    """The template itself, without its npm installs."""
    create = from_template(Path(languages.__file__).parent / "node" / "templates" / "express")
    create(tmp_path, StarterOptions("shop-back", "4", "20"))
    package = json.loads((tmp_path / "package.json").read_text())
    assert package["name"] == "shop-back" and package["engines"] == {"node": ">=20"}
    assert (tmp_path / ".nvmrc").read_text() == "20\n"
    assert (tmp_path / ".gitignore").exists() and (tmp_path / ".prettierignore").exists()
    assert "{{" not in "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())


# --------------------------------------------------------------------------- the real starters


# What a generated project must pass, by starter (the CI runs the same).
_NODE_CHECKS = [["npm", "test"], ["npm", "run", "lint"], ["npm", "run", "build"], ["npx", "prettier", "--check", "."]]
REAL_CHECKS = {
    "angular": [["npm", "run", "build"], ["npx", "prettier", "--check", "."]],
    "express": _NODE_CHECKS,
    "react": _NODE_CHECKS,
    "nextjs": _NODE_CHECKS,
    "fastapi": [["uv", "run", "pytest"], ["uv", "run", "ruff", "check", "."],
                ["uv", "run", "ruff", "format", "--check", "."]],
    "go": [["go", "vet", "./..."], ["go", "test", "./..."]],
}
# The dev server's (or the app's) forwarding of /api to the back-end, by front-end.
DEV_PROXY = {"angular": "proxy.conf.json", "react": "vite.config.ts", "nextjs": "src/proxy.ts"}


@pytest.mark.skipif(os.environ.get("QUOLL_NEW_TESTS") != "run", reason="set QUOLL_NEW_TESTS=run (npm, uv, network)")
@pytest.mark.parametrize("front, back, runtime", [
    ("angular", "express", []),
    ("angular@20", "express@4", ["--node", "22"]),
    ("react", "fastapi", []),
    ("nextjs", "go", []),
])
def test_real_starters(tmp_path, monkeypatch, front, back, runtime) -> None:
    monkeypatch.undo()  # the real starters
    args = ["--front", front, "--back", back, "--k8s", *runtime]
    result = runner.invoke(app, ["new", "shop", "-d", str(tmp_path), "--local", "-y", *args])
    assert result.exit_code == 0, result.output
    root = tmp_path / "shop"
    front_name, back_name = front.split("@")[0], back.split("@")[0]
    assert "/api" in (root / "front" / DEV_PROXY[front_name]).read_text()
    for part, name in (("front", front_name), ("back", back_name)):
        for check in REAL_CHECKS[name]:
            if "prettier" in check and "prettier" not in (root / part / "package.json").read_text():
                continue  # the project doesn't use Prettier: neither does its CI
            done = subprocess.run(check, cwd=root / part, capture_output=True, text=True)
            assert done.returncode == 0, f"{part}: {' '.join(check)}\n" + done.stdout[-3000:] + done.stderr[-3000:]
    for command in ("ci", "docker", "k8s"):
        assert runner.invoke(app, [command, "check", "-d", str(root)]).exit_code == 0


# --------------------------------------------------------------------------- starters, offline


def test_every_role_has_starters(monkeypatch) -> None:
    monkeypatch.undo()  # the real registry
    names = {role: [s.name for s in languages.starters(role)] for role in ("front", "back")}
    assert {"angular", "react", "nextjs"} <= set(names["front"])
    assert {"express", "fastapi", "go"} <= set(names["back"])
    # The next step `quoll new` prints: its own development command each.
    assert all(s.dev for s in languages.starters())
    assert {s.name: s.dev for s in languages.starters()}["go"] == "go run ."


def test_next_steps_use_each_starters_command(tmp_path, monkeypatch) -> None:
    from dataclasses import replace

    fakes = [replace(s, dev=f"run-{s.name}") for s in languages.starters()]
    monkeypatch.setattr(languages, "starters", lambda role="": [s for s in fakes if not role or s.role == role])
    result = _new(tmp_path, "--front", "web", "--back", "api")
    assert result.exit_code == 0, result.output
    assert "cd shop/front && run-web" in result.output and "cd shop/back && run-api" in result.output
    assert "npm" not in result.output


def test_go_template(tmp_path) -> None:
    from quoll.languages.go.starter import starter

    starter.create(tmp_path, StarterOptions("shop-api", "", "1.26"))
    assert (tmp_path / "go.mod").read_text() == "module shop-api\n\ngo 1.26\n"
    assert {"main.go", "main_test.go", "go.sum", ".gitignore", "README.md"} <= {p.name for p in tmp_path.iterdir()}
    assert "{{" not in "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())


def test_fastapi_template(tmp_path) -> None:
    """The template itself, without uv's installs."""
    import importlib

    starter = importlib.import_module("quoll.languages.python.frameworks.fastapi.starter")
    starter._copy(tmp_path, StarterOptions("shop-api", "", "3.13"))
    assert (tmp_path / ".python-version").read_text() == "3.13\n"
    assert 'requires-python = ">=3.13"' in (tmp_path / "pyproject.toml").read_text()
    assert '@app.get("/health")' in (tmp_path / "app/main.py").read_text()
    assert (tmp_path / "tests/test_main.py").exists() and (tmp_path / ".gitignore").exists()
    assert "{{" not in "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())


def test_react_dev_proxy(tmp_path) -> None:
    from quoll.languages.node.react import proxy

    (tmp_path / "vite.config.ts").write_text(
        'export default defineConfig({\n  plugins: [react()],\n});\n'
    )
    proxy(tmp_path, "/api", "http://localhost:8000", "BACK_URL")
    assert '  server: { proxy: { "/api": "http://localhost:8000" } },\n' in (tmp_path / "vite.config.ts").read_text()


@pytest.mark.parametrize("next_version, file", [("16.4.6", "proxy.ts"), ("^15.5.0", "middleware.ts")])
def test_nextjs_proxy_reads_the_url_at_runtime(tmp_path, next_version, file) -> None:
    from quoll.languages.node.frameworks.nextjs.starter import _standalone, proxy

    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"next": next_version}}))
    (tmp_path / "next.config.ts").write_text("const nextConfig: NextConfig = {\n};\n")
    _standalone(tmp_path)
    proxy(tmp_path, "/api", "http://localhost:8080", "BACK_URL")
    assert '  output: "standalone",' in (tmp_path / "next.config.ts").read_text()
    code = (tmp_path / "src" / file).read_text()
    assert f"export function {file[:-3]}(" in code
    assert 'process.env.BACK_URL ?? "http://localhost:8080"' in code and '"/api/:path*"' in code


# --------------------------------------------------------------------------- services


def test_services(tmp_path) -> None:
    result = _new(tmp_path, "--front", "web", "--back", "none", "--service", "orders=api", "--service", "users=api@1")
    assert result.exit_code == 0, result.output
    root = tmp_path / "shop"
    assert [c[:2] for c in calls] == [("front", "front"), ("back", "orders"), ("back", "users")]
    assert calls[2][2] == StarterOptions("users", "1", "")
    assert 'members = [\n    "front",\n    "services/orders",\n    "services/users",\n]' in (
        root / "quoll.toml").read_text()
    compose = yaml.safe_load((root / "compose.yaml").read_text())["services"]
    assert compose["orders"]["build"] == "./services/orders"
    assert compose["orders"]["environment"]["USERS_URL"].startswith("http://users:")
    assert compose["users"]["environment"]["ORDERS_URL"].startswith("http://orders:")
    # Same port in each container, different ones on the host.
    assert len({s["ports"][0].split(":")[0] for s in compose.values()}) == 3
    assert _forge_check(root)


def test_a_service_alone_is_the_repository(tmp_path) -> None:
    result = _new(tmp_path, "--front", "none", "--back", "none", "--service", "orders=api")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "shop" / "server.js").exists() and not (tmp_path / "shop" / "services").exists()


@pytest.mark.parametrize("spec, error", [
    ("orders", "expected NAME=STARTER"),
    ("Orders!=api", "expected NAME=STARTER"),
    ("orders=rails", "unknown starter 'rails'"),
])
def test_bad_service(tmp_path, spec, error) -> None:
    result = _new(tmp_path, "--service", spec)
    assert result.exit_code == 1 and error in result.output


def test_add_service(tmp_path) -> None:
    assert _new(tmp_path, "--front", "web", "--back", "api", "--cd").exit_code == 0
    root = tmp_path / "shop"
    result = runner.invoke(app, ["add", "service", "billing=api", "-d", str(root / "back")])  # from any member
    assert result.exit_code == 0, result.output
    assert (root / "services/billing/server.js").exists()
    assert '"services/billing",' in (root / "quoll.toml").read_text()
    config = (root / "services/billing/quoll.toml").read_text()
    assert "[ci]" in config and "[docker]" in config and "[cd]" in config  # the others publish: so does it
    jobs = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())["jobs"]
    assert {"billing-test", "billing-docker"} <= set(jobs)
    assert (root / ".github/workflows/cd-billing.yml").exists()
    compose = yaml.safe_load((root / "compose.yaml").read_text())["services"]
    assert compose["back"]["environment"]["BILLING_URL"].startswith("http://billing:")
    assert "/services/billing" in (root / ".github/dependabot.yml").read_text()  # untouched: kept up to date
    assert _forge_check(root)

    again = runner.invoke(app, ["add", "service", "billing=api", "-d", str(root)])
    assert again.exit_code == 1 and "already has a project named billing" in again.output


def test_remove_service(tmp_path) -> None:
    assert _new(tmp_path, "--front", "web", "--back", "api", "--cd").exit_code == 0
    root = tmp_path / "shop"
    assert runner.invoke(app, ["add", "service", "billing=api", "-d", str(root)]).exit_code == 0
    dependabot = root / ".github/dependabot.yml"
    dependabot.write_text(dependabot.read_text() + "# mine\n")

    result = runner.invoke(app, ["remove", "service", "billing", "-y", "-d", str(root)])
    assert result.exit_code == 1 and "uncommitted changes" in result.output  # never lose work
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "billing"], cwd=root, check=True)

    result = runner.invoke(app, ["remove", "service", "billing", "-y", "-d", str(root)])
    assert result.exit_code == 0, result.output
    assert not (root / "services").exists()
    assert '"services/billing"' not in (root / "quoll.toml").read_text()
    assert not (root / ".github/workflows/cd-billing.yml").exists()
    assert not (root / ".github/actions/quoll-setup-billing").exists()
    jobs = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())["jobs"]
    assert not any(j.startswith("billing-") for j in jobs)
    compose = yaml.safe_load((root / "compose.yaml").read_text())["services"]
    assert "billing" not in compose and "BILLING_URL" not in compose["back"]["environment"]
    # Edited by hand: left alone, with what to do.
    assert "/services/billing" in dependabot.read_text() and "dependabot.yml was edited" in result.output
    assert _forge_check(root)


def test_remove_unknown_service(tmp_path) -> None:
    assert _new(tmp_path, "--front", "web", "--back", "api").exit_code == 0
    result = runner.invoke(app, ["remove", "service", "nothing", "-y", "-d", str(tmp_path / "shop")])
    assert result.exit_code == 1 and "no project named nothing" in result.output


def test_remove_keeps_the_last_project(tmp_path) -> None:
    assert _new(tmp_path, "--front", "web", "--back", "api", "--platform", "gitlab", "--cd").exit_code == 0
    root = tmp_path / "shop"
    result = runner.invoke(app, ["remove", "service", "front", "--keep-files", "-d", str(root)])
    assert result.exit_code == 0, result.output
    assert (root / "front/package.json").exists()  # kept, out of the workspace
    assert "front-" not in (root / ".gitlab/quoll-ci.yml").read_text()
    result = runner.invoke(app, ["remove", "service", "back", "-y", "-d", str(root)])
    assert result.exit_code == 1 and "only project" in result.output


def test_add_service_to_a_single_project(tmp_path) -> None:
    assert _new(tmp_path, "--front", "none", "--back", "api").exit_code == 0
    result = runner.invoke(app, ["add", "service", "billing=api", "-d", str(tmp_path / "shop")])
    assert result.exit_code == 1 and "is a single project" in result.output


def _forge_check(root: Path) -> bool:
    """Everything quoll generated is up to date."""
    for command in (["ci", "check"], ["docker", "check"]):
        result = runner.invoke(app, [*command, "-d", str(root)])
        assert result.exit_code == 0, result.output
    return True


def test_services_keep_their_charts(tmp_path) -> None:
    """With charts, an added service gets its own (same namespaces), and the others learn its URL."""
    assert _new(tmp_path, "--front", "none", "--back", "api", "--service", "orders=api", "--cd").exit_code == 0
    root = tmp_path / "shop"
    assert runner.invoke(app, ["k8s", "init", "-y", "-d", str(root)]).exit_code == 0
    config = (root / "back/quoll.toml").read_text().replace('namespace = "shop-staging"', 'namespace = "qa"')
    (root / "back/quoll.toml").write_text(config)
    assert runner.invoke(app, ["k8s", "update", "-y", "-d", str(root)]).exit_code == 0
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "charts"], cwd=root, check=True)

    result = runner.invoke(app, ["add", "service", "billing=api", "-d", str(root)])
    assert result.exit_code == 0, result.output
    assert 'namespace = "qa"' in (root / "services/billing/quoll.toml").read_text()  # like the others
    assert (root / "services/billing/chart/templates/deployment.yaml").exists()
    back = yaml.safe_load((root / "back/chart/values.yaml").read_text())
    assert back["env"]["BILLING_URL"] == "http://billing:3000"
    assert "deploy-staging" in yaml.safe_load((root / ".github/workflows/cd-billing.yml").read_text())["jobs"]
    assert runner.invoke(app, ["k8s", "check", "-d", str(root)]).exit_code == 0

    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "billing"], cwd=root, check=True)
    assert runner.invoke(app, ["remove", "service", "billing", "-y", "-d", str(root)]).exit_code == 0
    assert "BILLING_URL" not in yaml.safe_load((root / "back/chart/values.yaml").read_text())["env"]
    assert runner.invoke(app, ["k8s", "check", "-d", str(root)]).exit_code == 0
