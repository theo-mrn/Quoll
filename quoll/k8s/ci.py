"""The CI's checks of a Helm chart, the same on both platforms: lint, Kubernetes schemas, misconfigurations."""
from __future__ import annotations

from typing import List

from quoll.ci.steps import Step, step
from quoll.ci.tools import TRIVY_VERSION

HELM_VERSION = "4.3.2"
HELM_IMAGE = f"alpine/helm:{HELM_VERSION}"
KUBECONFORM_VERSION = "0.8.0"
# Where the tools go: no root needed, the same path on GitHub runners and in GitLab's helm image.
_BIN = "/tmp/quoll-bin"

_KUBECONFORM = f"https://github.com/yannh/kubeconform/releases/download/v{KUBECONFORM_VERSION}"
_TRIVY = f"https://github.com/aquasecurity/trivy/releases/download/v{TRIVY_VERSION}"
_INSTALL = f"""mkdir -p {_BIN}
case "$(uname -m)" in x86_64) arch=amd64 trivy=64bit ;; *) arch=arm64 trivy=ARM64 ;; esac
wget -qO- "{_KUBECONFORM}/kubeconform-linux-$arch.tar.gz" | tar -xz -C {_BIN} kubeconform
wget -qO- "{_TRIVY}/trivy_{TRIVY_VERSION}_Linux-$trivy.tar.gz" | tar -xz -C {_BIN} trivy"""
# Every environment's values: the image is set by the deployment, any name renders the chart.
_LINT = """for values in {chart}/values-*.yaml; do
  helm lint --strict {chart} -f "$values" --set image.repository=ci
done"""
_SCHEMAS = """for values in {chart}/values-*.yaml; do
  echo "$values:"
  helm template ci {chart} -f "$values" --set image.repository=ci | {bin}/kubeconform -strict -summary
done"""
_SCAN = "{bin}/trivy config --exit-code 1 --severity HIGH,CRITICAL --helm-set image.repository=ci {chart}"


def chart_checks(chart: str) -> List[Step]:
    """Steps checking the chart in `chart` (helm installed)."""
    return [
        step("Install kubeconform and Trivy", run=_INSTALL),
        step("Lint chart", run=_LINT.format(chart=chart)),
        step("Kubernetes schemas", run=_SCHEMAS.format(chart=chart, bin=_BIN)),
        step("Misconfigurations", run=_SCAN.format(chart=chart, bin=_BIN)),
    ]
