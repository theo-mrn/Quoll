"""Deploying a published image with its Helm chart: the commands both platforms' delivery jobs run."""
from __future__ import annotations

from quoll.k8s.config import Environment, K8sConfig

# What the deploy jobs read: the image the delivery pushed, by digest (what was scanned, signed and attested).
IMAGE, DIGEST = "IMAGE", "DIGEST"


def helm_upgrade(k8s: K8sConfig, environment: str, settings: Environment) -> str:
    """Install or upgrade the release, wait until it is ready; roll it back otherwise."""
    return (
        f"helm upgrade --install {k8s.name} {k8s.chart} -f {k8s.chart}/values-{environment}.yaml \\\n"
        f"  --namespace {settings.namespace} --create-namespace \\\n"
        f'  --set image.repository="${IMAGE}" --set image.digest="${DIGEST}" \\\n'
        "  --rollback-on-failure --timeout 10m"
    )


def url(settings: Environment, tls: bool) -> str:
    """The environment's address, shown by the platform next to the deployment."""
    return f"{'https' if tls else 'http'}://{settings.host}" if settings.host else ""
