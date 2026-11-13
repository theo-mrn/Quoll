"""Turn a CDConfig into .github/workflows/cd.yml: build, scan with Trivy, then push.

In a workspace, every member with a [cd] gets its own workflow (cd-<member>.yml), run when its directory changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from quoll.cd.config import CDConfig
from quoll.ci.steps import Step, step
from quoll.ci.tools import SBOM_FILE, image_sbom
from quoll.files import PlannedFile, header, planned
from quoll.k8s.ci import HELM_VERSION
from quoll.k8s.config import Environment, K8sConfig
from quoll.k8s.deploy import DIGEST, IMAGE, helm_upgrade, url
from quoll.platforms.github.actions import ACTIONS, gha_cache_scope
from quoll.platforms.github.workflow import checkout, dump, render_steps
from quoll.workspace import Delivery

WORKFLOW_PATH = Path(".github/workflows/cd.yml")

_TAGS = """type=ref,event=branch
type=sha
type=semver,pattern={{version}}
type=semver,pattern={{major}}.{{minor}}
type=raw,value=latest,enable={{is_default_branch}}"""

# On v* tags: the release (created if needed, with generated notes) gets the image's SBOM.
_RELEASE = """case "$GITHUB_REF" in
  refs/tags/v*)
    if ! gh release view "$GITHUB_REF_NAME" >/dev/null 2>&1; then
      gh release create "$GITHUB_REF_NAME" --generate-notes --verify-tag
    fi
    gh release upload "$GITHUB_REF_NAME" sbom.cdx.json --clobber ;;
esac"""

# A workspace's members publish to the same release, possibly at the same time: each asset carries its name.
_MEMBER_RELEASE = """case "$GITHUB_REF" in
  refs/tags/v*)
    if ! gh release view "$GITHUB_REF_NAME" >/dev/null 2>&1; then
      # Another member may create it meanwhile.
      gh release create "$GITHUB_REF_NAME" --generate-notes --verify-tag \\
        || gh release view "$GITHUB_REF_NAME" >/dev/null
    fi
    cp sbom.cdx.json "{name}-sbom.cdx.json"
    gh release upload "$GITHUB_REF_NAME" "{name}-sbom.cdx.json" --clobber ;;
esac"""

_SUMMARY = """{
  echo "### Published"
  echo
  # shellcheck disable=SC2016 # Markdown's backquotes
  echo "$TAGS" | sed 's/^/- `/; s/$/`/'
} >> "$GITHUB_STEP_SUMMARY\""""


def render_workflow(cfg: CDConfig, name: str = "", directory: str = ".", k8s: Optional[K8sConfig] = None) -> str:
    """The delivery of a project, or of the workspace member `name` living in `directory`; deployed to each of
    `k8s`'s environments when it has a chart."""
    gha_cache = gha_cache_scope(name)
    push: Dict[str, Any] = {}
    if cfg.branches:
        push["branches"] = list(cfg.branches)
    if cfg.release_tags:
        push["tags"] = ["v*"]
    if name:
        # Branch pushes only publish what changed (tag pushes publish everything).
        push["paths"] = [f"{directory}/**", "quoll.toml", workflow_path(name).as_posix()]
    ghcr = cfg.registry == "ghcr"

    steps: List[Step] = [checkout()]
    if any(not p.endswith("amd64") for p in cfg.platforms):
        steps.append(step("Set up QEMU", uses=ACTIONS["setup-qemu"]))
    steps += [
        step("Set up Docker Buildx", uses=ACTIONS["setup-buildx"]),
        step(
            "Image metadata",
            id_="meta",
            uses=ACTIONS["metadata"],
            with_={"images": cfg.image, "tags": _TAGS},
        ),
    ]
    if cfg.scan:
        steps += [
            # Built and loaded locally first: a vulnerable image never reaches the registry.
            step(
                "Build image to scan",
                uses=ACTIONS["build-push"],
                with_={
                    "context": directory,
                    "platforms": cfg.platforms[0],
                    "load": True,
                    "tags": "scan:${{ github.sha }}",
                    "cache-from": gha_cache,
                    "cache-to": f"{gha_cache},mode=max",
                },
            ),
            step(
                "Scan image",
                uses=ACTIONS["trivy"],
                with_={
                    "image-ref": "scan:${{ github.sha }}",
                    "severity": ",".join(cfg.severity),
                    "ignore-unfixed": cfg.ignore_unfixed,
                    "exit-code": "1",
                },
            ),
        ]
    steps += [
        step(
            "Log in to the registry",
            uses=ACTIONS["login"],
            with_={"registry": "ghcr.io", "username": "${{ github.actor }}", "password": "${{ secrets.GITHUB_TOKEN }}"}
            if ghcr
            else {"username": "${{ secrets.DOCKERHUB_USERNAME }}", "password": "${{ secrets.DOCKERHUB_TOKEN }}"},
        ),
        step(
            "Push image",
            id_="push",
            uses=ACTIONS["build-push"],
            with_={
                "context": directory,
                "platforms": ",".join(cfg.platforms),
                "push": True,
                "tags": "${{ steps.meta.outputs.tags }}",
                "labels": "${{ steps.meta.outputs.labels }}",
                "cache-from": gha_cache,
                "cache-to": f"{gha_cache},mode=max",
                # Supply-chain metadata stored next to the image.
                "provenance": "mode=max",
                "sbom": True,
            },
        ),
    ]
    steps += _supply_chain(cfg, ghcr, name, directory)
    steps.append(step("Summary", run=_SUMMARY, env={"TAGS": "${{ steps.meta.outputs.tags }}"}))

    permissions = {"contents": "read"}
    if cfg.sbom and cfg.release_tags:
        permissions["contents"] = "write"  # attach the SBOM to the release
    if ghcr:
        permissions["packages"] = "write"
    if cfg.sign:
        permissions.update({"id-token": "write", "attestations": "write", "artifact-metadata": "write"})
    job: Dict[str, Any] = {
        "name": "Build, scan and push the image" if cfg.scan else "Build and push the image",
        "runs-on": "ubuntu-latest",
        "timeout-minutes": 30,
        "permissions": permissions,
    }
    if directory != ".":
        job["defaults"] = {"run": {"working-directory": directory}}
    if k8s and k8s.environments:
        job["outputs"] = {"digest": "${{ steps.push.outputs.digest }}"}
    job["steps"] = render_steps(steps)
    jobs = {"image": job}
    for environment, settings in (k8s.environments.items() if k8s else ()):
        jobs[f"deploy-{environment}"] = _deploy_job(cfg, k8s, environment, settings, name, directory)
    doc = {
        "name": f"CD ({name})" if name else "CD",
        "on": {"push": push, "workflow_dispatch": None},
        "permissions": {"contents": "read"},
        # Never cancel a publication halfway; queue the next one instead.
        "concurrency": {"group": "${{ github.workflow }}-${{ github.ref }}", "cancel-in-progress": False},
        "jobs": jobs,
    }
    return header("cd") + dump(doc)


def _deploy_job(
    cfg: CDConfig, k8s: K8sConfig, environment: str, settings: Environment, name: str, directory: str
) -> Dict[str, Any]:
    """Deploy the image just published, by digest, once its signature checks out. KUBECONFIG is a secret of the
    GitHub environment: a cluster each; protect production's with required reviewers."""
    on = "github.ref_type == 'branch'" if settings.deploy_on == "branch" else "startsWith(github.ref, 'refs/tags/v')"
    env = {IMAGE: cfg.image, DIGEST: "${{ needs.image.outputs.digest }}"}
    helm = step("Set up Helm", uses=ACTIONS["setup-helm"], with_={"version": f"v{HELM_VERSION}"})
    steps: List[Step] = [checkout(), helm]
    if cfg.sign:
        verify = f'gh attestation verify "oci://{_registry_name(cfg.image)}@${DIGEST}" --repo "$GITHUB_REPOSITORY"'
        steps.append(step("Verify the image's provenance", run=verify, env={**env, "GH_TOKEN": "${{ github.token }}"}))
    deploy = f"{_KUBECONFIG}\n{helm_upgrade(k8s, environment, settings)}"
    kubeconfig = {"KUBECONFIG_DATA": "${{ secrets.KUBECONFIG }}"}
    steps.append(step(f"Deploy to {environment}", run=deploy, env={**env, **kubeconfig}))
    target: Dict[str, Any] = {"name": environment}
    address = url(settings, k8s.tls)
    if address:
        target["url"] = address
    job: Dict[str, Any] = {
        "name": f"Deploy to {environment}",
        "needs": "image",
        "if": "${{ " + on + " }}",
        "runs-on": "ubuntu-latest",
        "timeout-minutes": 15,
        "environment": target,
        # One deployment at a time per environment; the next one waits.
        "concurrency": {"group": f"deploy-{environment}-{name or 'app'}", "cancel-in-progress": False},
        "permissions": {"contents": "read", "attestations": "read"},
    }
    if directory != ".":
        job["defaults"] = {"run": {"working-directory": directory}}
    job["steps"] = render_steps(steps)
    return job


def _supply_chain(cfg: CDConfig, ghcr: bool, name: str = "", directory: str = ".") -> List[Step]:
    """SBOM of what was pushed (by digest), signed attestations, the SBOM attached to the release."""
    # Commands run in the project's directory; actions' paths are given from the repository root.
    sbom_path = SBOM_FILE if directory == "." else f"{directory}/{SBOM_FILE}"
    digest = "${{ steps.push.outputs.digest }}"
    steps: List[Step] = []
    if cfg.sbom:
        user, password = (
            ("${{ github.actor }}", "${{ secrets.GITHUB_TOKEN }}")
            if ghcr
            else ("${{ secrets.DOCKERHUB_USERNAME }}", "${{ secrets.DOCKERHUB_TOKEN }}")
        )
        credentials = {"TRIVY_USERNAME": user, "TRIVY_PASSWORD": password}
        steps += [
            step("SBOM of the image", run=image_sbom(), env={"IMAGE": cfg.image, "DIGEST": digest, **credentials}),
            step(
                "Upload SBOM",
                uses=ACTIONS["upload-artifact"],
                with_={"name": f"{name}-image-sbom" if name else "image-sbom", "path": sbom_path},
            ),
        ]
    if cfg.sign:
        subject = {"subject-name": _registry_name(cfg.image), "subject-digest": digest, "push-to-registry": True}
        steps.append(step("Attest build provenance", uses=ACTIONS["attest"], with_=subject))
        if cfg.sbom:
            steps.append(step("Attest SBOM", uses=ACTIONS["attest"], with_={**subject, "sbom-path": sbom_path}))
    if cfg.sbom and cfg.release_tags:
        release = _MEMBER_RELEASE.format(name=name) if name else _RELEASE
        steps.append(step("Attach the SBOM to the release", run=release, env={"GH_TOKEN": "${{ github.token }}"}))
    return steps


def _registry_name(image: str) -> str:
    """Fully qualified name: Docker Hub images are attested as index.docker.io/<name>."""
    first = image.split("/", 1)[0]
    return image if "." in first or ":" in first else f"index.docker.io/{image}"


# The environment's kubeconfig, from its secret, for helm.
_KUBECONFIG = """export KUBECONFIG="$RUNNER_TEMP/kubeconfig"
printf '%s' "$KUBECONFIG_DATA" > "$KUBECONFIG"
chmod 600 "$KUBECONFIG\""""


def workflow_path(name: str = "") -> Path:
    return Path(f".github/workflows/cd-{name}.yml") if name else WORKFLOW_PATH


def plan(project_dir: Path, deliveries: Union[CDConfig, List[Delivery]]) -> List[PlannedFile]:
    if isinstance(deliveries, CDConfig):
        deliveries = [Delivery("", ".", deliveries)]
    return [
        planned(project_dir, workflow_path(d.name), render_workflow(d.cfg, d.name, d.directory, d.k8s))
        for d in deliveries
    ]
