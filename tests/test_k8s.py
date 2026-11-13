"""`quoll k8s`: a Helm chart per project, checked by the CI, deployed by the delivery. Charts are linted with the
local helm when there is one; QUOLL_K8S_TESTS=run deploys them on a kind cluster (tests/k8s)."""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest
import yaml
from typer.testing import CliRunner

from quoll.docker.config import DockerConfig
from quoll.k8s.config import K8sConfig, default_environments
from quoll.k8s.render import render_values
from quoll.main import app
from tests.helpers import actionlint, dockerfile, gitlab_lint, load
from tests.samples import ALL_PROJECTS, FASTAPI, NEXTJS

runner = CliRunner()
HELM = shutil.which("helm")


def _quoll(*args: str):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result


def _helm_lint(chart) -> None:
    if not HELM:
        return
    for values in sorted(chart.glob("values-*.yaml")):
        lint = subprocess.run([HELM, "lint", "--strict", str(chart), "-f", str(values), "--set",
                               "image.repository=ci"], capture_output=True, text=True)
        assert lint.returncode == 0, lint.stdout + lint.stderr
        rendered = subprocess.run([HELM, "template", "ci", str(chart), "-f", str(values), "--set",
                                   "image.repository=ci"], capture_output=True, text=True, check=True).stdout
        kinds = [doc["kind"] for doc in yaml.safe_load_all(rendered) if doc]
        assert {"Deployment", "Service", "ServiceAccount"} <= set(kinds)


def _project(make_project, files, remote="git@github.com:acme/shop.git"):
    root = make_project(files)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)
    return root


def test_single_project(make_project, tmp_path) -> None:
    root = _project(make_project, {**FASTAPI, "app/main.py": '@app.get("/healthz")\ndef health(): ...\n'})
    _quoll("ci", "init", "-y", "-d", str(root))
    _quoll("docker", "init", "-y", "-d", str(root))
    result = _quoll("k8s", "init", "-y", "-d", str(root))
    assert "helm upgrade --install project" in result.output

    config = (root / "quoll.toml").read_text()
    assert '[k8s]\nname = "project"' in config and 'health_path = "/healthz"' in config  # found in the code
    assert '[k8s.environments.staging]\nnamespace = "project-staging"\ndeploy_on = "branch"' in config
    assert '[k8s.environments.production]\nnamespace = "project"\ndeploy_on = "tag"' in config
    assert 'chart = "chart"' in config.split("[k8s]")[0]  # the CI checks it

    values = yaml.safe_load((root / "chart/values.yaml").read_text())
    assert values["port"] == 8000 and values["healthPath"] == "/healthz"
    assert values["readOnlyRootFilesystem"] is True and values["writablePaths"] == ["/tmp"]
    assert values["envFromSecret"] == "project-env"
    assert yaml.safe_load((root / "chart/values-production.yaml").read_text()) == {"replicaCount": 2}
    _helm_lint(root / "chart")

    jobs = load((root / ".github/workflows/ci.yml").read_text())["jobs"]
    names = [s.get("name") for s in jobs["chart"]["steps"]]
    assert names[1:] == ["Set up Helm", "Install kubeconform and Trivy", "Lint chart", "Kubernetes schemas",
                         "Misconfigurations"]
    actionlint(tmp_path, (root / ".github/workflows/ci.yml").read_text())
    _quoll("ci", "check", "-d", str(root))
    _quoll("k8s", "check", "-d", str(root))

    # A setting changed in quoll.toml: the chart follows, `check` notices until then.
    (root / "quoll.toml").write_text(config.replace('memory = "256Mi"', 'memory = "1Gi"'))
    assert runner.invoke(app, ["k8s", "check", "-d", str(root)]).exit_code == 1
    _quoll("k8s", "update", "-y", "-d", str(root))
    assert yaml.safe_load((root / "chart/values.yaml").read_text())["resources"]["requests"]["memory"] == "1Gi"


def test_requires_docker(make_project) -> None:
    root = _project(make_project, FASTAPI)
    result = runner.invoke(app, ["k8s", "init", "-y", "-d", str(root)])
    assert result.exit_code == 1 and "quoll docker init" in result.output


@pytest.mark.parametrize("remote", ["git@github.com:acme/shop.git", "git@gitlab.com:acme/shop.git"])
def test_workspace_deploys_every_project(make_project, tmp_path, remote) -> None:
    files = {**{f"backend/{k}": v for k, v in FASTAPI.items()}, **{f"frontend/{k}": v for k, v in NEXTJS.items()}}
    root = _project(make_project, files, remote)
    for command in ("ci", "docker", "cd", "k8s"):
        _quoll(command, "init", "-y", "-d", str(root))

    # Each project reaches the others at their Service, in the same namespace.
    frontend = yaml.safe_load((root / "frontend/chart/values.yaml").read_text())
    assert frontend["env"] == {"BACKEND_URL": "http://backend:8000"}
    assert frontend["writablePaths"] == ["/tmp", "/app/.next/cache"]
    for member in ("backend", "frontend"):
        assert 'namespace = "project-staging"' in (root / member / "quoll.toml").read_text()
        _helm_lint(root / member / "chart")

    if "github" in remote:
        text = (root / ".github/workflows/cd-backend.yml").read_text()
        jobs = load(text)["jobs"]
        assert jobs["image"]["outputs"] == {"digest": "${{ steps.push.outputs.digest }}"}
        staging, production = jobs["deploy-staging"], jobs["deploy-production"]
        assert staging["needs"] == "image" and staging["if"] == "${{ github.ref_type == 'branch' }}"
        assert production["if"] == "${{ startsWith(github.ref, 'refs/tags/v') }}"
        assert staging["environment"] == {"name": "staging"}
        assert staging["defaults"] == {"run": {"working-directory": "backend"}}
        verify, deploy = staging["steps"][-2], staging["steps"][-1]
        assert verify["run"].startswith('gh attestation verify "oci://ghcr.io/acme/shop-backend@$DIGEST"')
        assert "helm upgrade --install backend chart -f chart/values-staging.yaml" in deploy["run"]
        assert "--namespace project-staging --create-namespace" in deploy["run"]
        assert deploy["env"]["KUBECONFIG_DATA"] == "${{ secrets.KUBECONFIG }}"
        assert deploy["run"].index("No KUBECONFIG secret") < deploy["run"].index("helm upgrade")
        actionlint(tmp_path, text)
        ci = load((root / ".github/workflows/ci.yml").read_text())["jobs"]
        assert {"backend-chart", "frontend-chart"} <= set(ci)
    else:
        text = (root / ".gitlab/cd.yml").read_text()
        cd = yaml.safe_load(text)
        assert cd["backend-publish"]["artifacts"]["reports"]["dotenv"] == "backend/deploy.env"
        assert cd["backend-publish"]["script"][-1] == 'echo "DIGEST=$DIGEST" > deploy.env'
        staging, production = cd["backend-deploy-staging"], cd["backend-deploy-production"]
        assert staging["stage"] == "deploy" and staging["needs"] == [{"job": "backend-publish", "artifacts": True}]
        # Where the image was published from: the branch, when the project changed.
        assert staging["rules"][1]["if"] == '$CI_COMMIT_BRANCH == "main"' and "changes" in staging["rules"][1]
        assert production["rules"][-1] == {"if": "$CI_COMMIT_TAG =~ /^v/", "when": "manual"}
        assert staging["environment"] == {"name": "staging", "action": "start"}
        script = "\n".join(staging["script"])
        assert script.index("cosign verify") < script.index("helm upgrade --install backend")
        assert script.index('[ -n "${KUBECONFIG:-}" ]') < script.index("helm upgrade --install backend")
        gitlab_lint(tmp_path, text, "cd.yml")
        root_pipeline = (root / ".gitlab-ci.yml").read_text()
        assert yaml.safe_load(root_pipeline)["stages"] == ["test", "publish", "deploy"]
        gitlab_lint(tmp_path, root_pipeline)
        assert "backend-chart" in yaml.safe_load((root / ".gitlab/quoll-ci.yml").read_text())
    _quoll("cd", "check", "-d", str(root / "backend"))
    _quoll("k8s", "check", "-d", str(root))


def test_ingress_and_autoscaling() -> None:
    docker = DockerConfig(stack="python", framework="fastapi", package_manager="uv", version="3.13",
                          command="uvicorn app.main:app")
    k8s = K8sConfig(name="api", max_replicas=6, cluster_issuer="letsencrypt", environments=default_environments("shop"))
    values = yaml.safe_load(render_values(k8s, docker, "ghcr.io/acme/api"))
    assert values["autoscaling"] == {"enabled": True, "minReplicas": 1, "maxReplicas": 6,
                                     "targetCPUUtilizationPercentage": 80}
    assert values["ingress"]["annotations"] == {"cert-manager.io/cluster-issuer": "letsencrypt"}
    assert values["image"]["repository"] == "ghcr.io/acme/api"


@pytest.mark.parametrize("name", list(ALL_PROJECTS))
def test_images_run_as_a_numeric_user(make_project, name) -> None:
    """Kubernetes checks runAsNonRoot on numeric users only: every image's last USER is one."""
    text = dockerfile(make_project, ALL_PROJECTS[name])
    user = re.findall(r"^USER (\S+)$", text, re.MULTILINE)[-1]
    assert re.fullmatch(r"(\d+(:\d+)?|\$APP_UID)", user), user


@pytest.mark.parametrize("config, error", [
    ({"name": "Shop API"}, "isn't a valid Kubernetes name"),
    ({"name": "api", "health_path": "health"}, "should start with /"),
    ({"name": "api", "environments": {"prod": {"namespace": "x", "deploy_on": "friday"}}}, "deploy_on"),
])
def test_invalid_config(config, error) -> None:
    with pytest.raises(ValueError, match=error):
        K8sConfig.model_validate(config)


def test_without_ci(make_project) -> None:
    root = _project(make_project, FASTAPI)
    _quoll("docker", "init", "-y", "-d", str(root))
    _quoll("k8s", "init", "-y", "-d", str(root))
    assert (root / "chart/Chart.yaml").exists() and not (root / ".github").exists()
