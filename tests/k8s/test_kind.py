"""Deploy real applications with their generated Helm charts on a kind cluster, with the delivery's own command.

Slow (builds every image, starts a cluster), so opt-in; needs docker, kind, helm and kubectl:

    QUOLL_K8S_TESTS=run pytest tests/k8s
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quoll.k8s.config import load_config
from quoll.k8s.deploy import helm_upgrade
from quoll.main import app
from tests.docker.test_build import APPS, _wait_for_http

pytestmark = pytest.mark.skipif(
    os.environ.get("QUOLL_K8S_TESTS") != "run" or not all(shutil.which(t) for t in ("kind", "helm", "kubectl")),
    reason="set QUOLL_K8S_TESTS=run (with kind, helm and kubectl) to deploy on a kind cluster",
)

CLUSTER = "quoll-test"


@pytest.fixture(scope="module")
def cluster():
    existing = subprocess.run(["kind", "get", "clusters"], capture_output=True, text=True).stdout.split()
    if CLUSTER not in existing:
        subprocess.run(["kind", "create", "cluster", "--name", CLUSTER, "--wait", "180s"], check=True,
                       capture_output=True)
    yield f"kind-{CLUSTER}"
    if CLUSTER not in existing:
        subprocess.run(["kind", "delete", "cluster", "--name", CLUSTER], capture_output=True)


@pytest.mark.parametrize("name", list(APPS))
def test_chart_deploys_and_serves(tmp_path, cluster, name) -> None:
    spec = APPS[name]
    root = tmp_path / name
    root.mkdir()
    spec.create(root)
    args = ["docker", "init", "-y", "--force", "-d", str(root)] + (["--command", spec.command] if spec.command else [])
    for command in (args, ["k8s", "init", "-y", "-d", str(root)]):
        result = CliRunner().invoke(app, command)
        assert result.exit_code == 0, result.output
    k8s = load_config(root)

    image = f"quoll-test-{name}-{uuid.uuid4().hex[:8]}"
    build = subprocess.run(["docker", "build", "-q", "-t", f"{image}:latest", str(root)], capture_output=True,
                           text=True)
    assert build.returncode == 0, build.stderr[-4000:]
    namespace = k8s.environments["staging"].namespace
    try:
        subprocess.run(["kind", "load", "docker-image", "--name", CLUSTER, f"{image}:latest"], check=True,
                       capture_output=True)
        # The delivery's command, as generated: the image by digest there; here the loaded image (no digest).
        command = helm_upgrade(k8s, "staging", k8s.environments["staging"])
        command += "".join(f" --set env.{key}={value}" for key, value in spec.env.items())
        deploy = subprocess.run(["sh", "-c", command], cwd=root, capture_output=True, text=True, env={
            **os.environ, "IMAGE": image, "DIGEST": "", "HELM_KUBECONTEXT": cluster,
        })
        if deploy.returncode != 0:
            pods = subprocess.run(["kubectl", "--context", cluster, "-n", namespace, "describe", "pods"],
                                  capture_output=True, text=True).stdout
            logs = subprocess.run(["kubectl", "--context", cluster, "-n", namespace, "logs", f"deploy/{k8s.name}",
                                   "--tail", "50"], capture_output=True, text=True)
            pytest.fail(deploy.stdout + deploy.stderr + pods[-3000:] + logs.stdout + logs.stderr)
        assert _served(cluster, namespace, k8s.name, root)
    finally:
        subprocess.run(["kubectl", "--context", cluster, "delete", "namespace", namespace, "--wait=false"],
                       capture_output=True)
        subprocess.run(["docker", "rmi", "-f", f"{image}:latest"], capture_output=True)


def _served(cluster: str, namespace: str, name: str, root: Path) -> bool:
    """GET / through the Service answers without a server error."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    from quoll.docker.config import load_config as load_docker_config

    target = load_docker_config(root).port
    forward = subprocess.Popen(
        ["kubectl", "--context", cluster, "-n", namespace, "port-forward", f"svc/{name}", f"{port}:{target}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(2)
        status = _wait_for_http(str(port), timeout=60)
        assert status is not None and status < 500, f"status={status}"
        return True
    finally:
        forward.terminate()
