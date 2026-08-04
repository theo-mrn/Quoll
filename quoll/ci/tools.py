"""Language-independent CI tools (secret scanning, static analysis, image checks), shared by the platforms.

Images are pinned; both platforms run the same commands, GitHub in a container job or on the runner, GitLab in a
container job.
"""
from __future__ import annotations

from typing import List

from quoll.ci.steps import Step, step
from quoll.platforms.github.actions import ACTIONS

GITLEAKS_IMAGE = "ghcr.io/gitleaks/gitleaks:v8.30.1"
SEMGREP_IMAGE = "semgrep/semgrep:1.185.0"
TRIVY_VERSION = "0.76.2"
TRIVY_IMAGE = f"aquasec/trivy:{TRIVY_VERSION}"
SBOM_FILE = "sbom.cdx.json"

# Fixable vulnerabilities of these severities fail the image scan (same defaults as [cd]).
IMAGE_SCAN_SEVERITY = "CRITICAL,HIGH"


_OSV_SCANNER = """arch=$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')
curl -sSfL -o /usr/local/bin/osv-scanner \\
  "https://github.com/google/osv-scanner/releases/latest/download/osv-scanner_linux_$arch"
chmod +x /usr/local/bin/osv-scanner"""


def install_osv_scanner() -> Step:
    """osv-scanner reads lock files of many ecosystems (Maven, Gradle, Conan...)."""
    return step("Install osv-scanner", run=_OSV_SCANNER, uses=ACTIONS["install-tool"], with_={"tool": "osv-scanner"})


# The release binary, pinned (no install script fetched from a branch); curl comes from apt in slim images.
_TRIVY_INSTALL = """if ! command -v curl >/dev/null; then
  apt-get update -qq && apt-get install -y -qq curl ca-certificates
fi
arch=$(uname -m | sed 's/x86_64/64bit/; s/aarch64/ARM64/')
mkdir -p /tmp/trivy
curl -sSfL "https://github.com/aquasecurity/trivy/releases/download/v{v}/trivy_{v}_Linux-$arch.tar.gz" \\
  | tar -xz -C /tmp/trivy trivy"""


# Tool caches the container jobs keep in the project (see CISteps.cache): not dependencies of the project.
_TOOL_CACHES = (".go", ".cargo", ".m2", ".gradle", ".cache", ".npm", ".pnpm-store", ".yarn/cache", ".yarn-cache",
                ".nuget", ".sonar", "build")


def dependency_checks(sbom: bool, licenses: bool, severities: List[str]) -> List[Step]:
    """SBOM and license gate, run once the dependencies are installed: `trivy rootfs` reads the installed packages
    (node_modules, .venv, vendor/, jars...), where the licenses are; lock files alone don't carry them."""
    trivy = f"/tmp/trivy/trivy rootfs --quiet --skip-dirs {','.join(_TOOL_CACHES)}"
    steps = [step("Install Trivy", run=_TRIVY_INSTALL.format(v=TRIVY_VERSION))]
    if sbom:
        steps.append(step("SBOM (CycloneDX)", run=f"{trivy} --format cyclonedx --output {SBOM_FILE} ."))
    if licenses:
        # Trivy's categories: CRITICAL = forbidden (AGPL, SSPL...), HIGH = restricted (GPL, LGPL),
        # MEDIUM = reciprocal (MPL, EPL), LOW = notice (MIT, Apache, BSD).
        steps.append(
            step(
                "License check",
                # Every license is listed; only the configured categories fail. Free-text licenses Trivy can't
                # classify are UNKNOWN.
                run=f"{trivy} --scanners license --severity {','.join(severities)} --exit-code 1 .",
            )
        )
    return steps


def image_sbom() -> str:
    """Shell command writing the SBOM of the pushed image $IMAGE@$DIGEST (registry credentials in
    TRIVY_USERNAME / TRIVY_PASSWORD) to SBOM_FILE. Trivy runs as a container: works on runners and in dind."""
    return (
        f"docker run --rm -e TRIVY_USERNAME -e TRIVY_PASSWORD {TRIVY_IMAGE} image --quiet --format cyclonedx "
        f'"$IMAGE@$DIGEST" > {SBOM_FILE}'
    )


def secret_scan() -> Step:
    """Every commit of the history, so a secret removed later is still caught (allow-list: .gitleaksignore)."""
    return step("Secret scanning", run="gitleaks git --redact --verbose .")


def sast(report: str = "") -> Step:
    """Semgrep's default rules for every language of the repository; `report` also writes GitLab's SAST report."""
    # Blocking: ERROR rules only; WARNING ones are mostly low-confidence "audit" rules, noise in a gate.
    command = "semgrep scan --config p/default --severity ERROR --error --metrics off"
    if report:
        command += f" --text --gitlab-sast-output={report}"
    # An explicit target: without one, semgrep's image expects the code mounted at /src.
    return step("Static analysis", run=command + " .")


def image_checks(tag: str) -> List[Step]:
    """Lint the Dockerfile (BuildKit's checks), build the image, scan it with Trivy before anyone ships it."""
    scan = (
        f"docker run --rm -v /var/run/docker.sock:/var/run/docker.sock {TRIVY_IMAGE} image --no-progress "
        f'--exit-code 1 --severity {IMAGE_SCAN_SEVERITY} --ignore-unfixed "{tag}"'
    )
    return [
        step("Lint Dockerfile", run="docker build --check ."),
        step("Build image", run=f'docker build --tag "{tag}" .'),
        step("Scan image", run=scan),
    ]
