"""Turn a CDConfig into .gitlab/cd.yml: build, scan with Trivy, then push.

.gitlab-ci.yml (`quoll ci`) includes this file. Its job runs in the `publish` stage, so only once every CI job
of the pipeline passed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

from quoll.cd.config import CDConfig
from quoll.ci.tools import SBOM_FILE, TRIVY_IMAGE, image_sbom
from quoll.files import PlannedFile, header, planned
from quoll.k8s.ci import HELM_IMAGE
from quoll.k8s.config import Environment
from quoll.k8s.deploy import DIGEST, IMAGE, helm_upgrade, url
from quoll.platforms.gitlab.ci import CD_PATH, SCHEDULED
from quoll.platforms.gitlab.pipeline import branch_rule, docker_job, dump, registry_cache
from quoll.workspace import Delivery

PIPELINE_PATH = Path(CD_PATH)

# Same tags as docker/metadata-action on GitHub: branch, sha-<sha>, latest on the default branch,
# 1.2.3 and 1.2 for a v1.2.3 tag (plus latest unless it is a pre-release).
_TAGS = """tags="sha-$CI_COMMIT_SHORT_SHA"
if [ -n "$CI_COMMIT_TAG" ]; then
  version="${CI_COMMIT_TAG#v}"
  case "$version" in
    *-*) tags="$tags $version" ;;
    *) tags="$tags $version ${version%.*} latest" ;;
  esac
else
  tags="$tags $CI_COMMIT_REF_SLUG"
  if [ "$CI_COMMIT_BRANCH" = "$CI_DEFAULT_BRANCH" ]; then tags="$tags latest"; fi
fi
tag_args=""
for tag in $tags; do tag_args="$tag_args --tag $IMAGE:$tag"; done"""

# The scanner runs as a container of the Docker-in-Docker daemon, next to the image it scans.
_SCAN = (
    "docker run --rm -v /var/run/docker.sock:/var/run/docker.sock {trivy} image --no-progress --exit-code 1 "
    '--severity {severity}{unfixed} "scan:$CI_COMMIT_SHA"'
)

# The digest buildx pushed, from its metadata file.
_DIGEST = """DIGEST=$(sed -n 's/.*"containerimage.digest": *"\\([^"]*\\)".*/\\1/p' metadata.json | head -n 1)
echo "Digest: $DIGEST\""""
# Variables the publish job hands to the deploy jobs.
DEPLOY_ENV = "deploy.env"
# `release:` runs through glab.
GLAB_IMAGE = "registry.gitlab.com/gitlab-org/cli:v1.130.0"

_LOGIN = {
    "gitlab": 'echo "$CI_REGISTRY_PASSWORD" | docker login --username "$CI_REGISTRY_USER" --password-stdin '
    '"$CI_REGISTRY"',
    "dockerhub": 'echo "$DOCKERHUB_TOKEN" | docker login --username "$DOCKERHUB_USERNAME" --password-stdin',
}


def render_pipeline(target: Union[CDConfig, List[Delivery]]) -> str:
    """The delivery of a project, or of each workspace member with a [cd] (when its directory changed)."""
    deliveries = [Delivery("", ".", target)] if isinstance(target, CDConfig) else target
    # Not "image": a reserved top-level keyword.
    doc: Dict[str, Any] = {_publish_job(d): _publish(d) for d in deliveries}
    for d in deliveries:
        for environment, settings in (d.k8s.environments.items() if d.k8s else ()):
            job = f"{d.name}-deploy-{environment}" if d.name else f"deploy-{environment}"
            doc[job] = _deploy(d, environment, settings)
    released = [d for d in deliveries if d.cfg.sbom and d.cfg.release_tags]
    if released:
        doc["release"] = _release(released)
    return header("cd") + dump(doc)


def _publish(delivery: Delivery) -> Dict[str, Any]:
    cfg, name, directory = delivery.cfg, delivery.name, delivery.directory
    branches = [branch_rule(b) for b in cfg.branches]
    if name and directory != ".":
        # Branch pushes only publish what changed (tag pipelines count everything as changed).
        changes = {"paths": [f"{directory}/**/*", "quoll.toml", ".gitlab-ci.yml", ".gitlab/**/*"]}
        branches = [{**rule, "changes": changes} for rule in branches]
    # Never from a scheduled pipeline (quoll ci's security scans run on the default branch).
    rules: List[Dict[str, Any]] = [{"if": SCHEDULED, "when": "never"}, *branches]
    if cfg.release_tags:
        rules.append({"if": "$CI_COMMIT_TAG =~ /^v/"})

    script = [_TAGS]
    if any(not p.endswith("amd64") for p in cfg.platforms):
        script.append("docker run --privileged --rm tonistiigi/binfmt --install all")
    # A container builder (multi-platform images, provenance and SBOM attestations), with the layers the CI's docker
    # job cached in the project's registry.
    script.append(registry_cache(name or "ci"))
    if cfg.scan:
        script += [
            # Built and loaded locally first: a vulnerable image never reaches the registry.
            f'docker buildx build --platform {cfg.platforms[0]} --load $cache --tag "scan:$CI_COMMIT_SHA" .',
            _SCAN.format(
                trivy=TRIVY_IMAGE,
                severity=",".join(cfg.severity),
                unfixed=" --ignore-unfixed" if cfg.ignore_unfixed else "",
            ),
        ]
    gitlab = cfg.registry == "gitlab"
    script += [
        _LOGIN["gitlab" if gitlab else "dockerhub"],
        # Supply-chain metadata stored next to the image; the metadata file gives the pushed digest.
        f"docker buildx build --platform {','.join(cfg.platforms)} --push $cache --provenance=mode=max --sbom=true "
        "--metadata-file metadata.json $tag_args .",
        _DIGEST,
    ]
    if cfg.sbom:
        user, password = ("$CI_REGISTRY_USER", "$CI_REGISTRY_PASSWORD") if gitlab else (
            "$DOCKERHUB_USERNAME", "$DOCKERHUB_TOKEN"
        )
        script.append(f'TRIVY_USERNAME="{user}" TRIVY_PASSWORD="{password}" {image_sbom()}')
    if cfg.sign:
        script += [
            "apk add --no-cache cosign",
            # Keyless: the job's OIDC token (id_tokens below) is the identity, recorded in Sigstore's public log.
            'cosign sign --yes "$IMAGE@$DIGEST"',
        ]
        if cfg.sbom:
            script.append(f'cosign attest --yes --type cyclonedx --predicate {SBOM_FILE} "$IMAGE@$DIGEST"')
    script.append('echo "Published:"; for tag in $tags; do echo "  $IMAGE:$tag"; done; echo "  $IMAGE@$DIGEST"')
    if delivery.k8s and delivery.k8s.environments:
        # For the deploy jobs (a dotenv report becomes their variables).
        script.append(f'echo "{DIGEST}=$DIGEST" > {DEPLOY_ENV}')

    publish = docker_job(
        "publish",
        script,
        timeout=30,
        directory=directory,
        rules=rules,
        variables={"IMAGE": cfg.image},
        # Never cancel a publication halfway, and never run two at once.
        interruptible=False,
        resource_group=f"publish-{name}" if name else "publish",
    )
    if cfg.sign:
        publish["id_tokens"] = {"SIGSTORE_ID_TOKEN": {"aud": "sigstore"}}
    if cfg.sbom:
        sbom = _sbom_path(delivery)
        publish["artifacts"] = {"paths": [sbom], "reports": {"cyclonedx": [sbom]}, "expire_in": "1 week"}
    if delivery.k8s and delivery.k8s.environments:
        reports = publish.setdefault("artifacts", {"expire_in": "1 week"}).setdefault("reports", {})
        reports["dotenv"] = DEPLOY_ENV if directory == "." else f"{directory}/{DEPLOY_ENV}"
    return publish


def _publish_job(delivery: Delivery) -> str:
    return f"{delivery.name}-publish" if delivery.name else "publish"


def _deploy(delivery: Delivery, environment: str, settings: Environment) -> Dict[str, Any]:
    """Deploy the image just published, by digest, once its signature checks out. KUBECONFIG is a file variable
    scoped to the environment: a cluster each."""
    cfg, k8s, directory = delivery.cfg, delivery.k8s, delivery.directory
    publish_rules = _publish(delivery)["rules"]
    if settings.deploy_on == "branch":
        # Where the image is published from a branch (and the project changed, in a workspace).
        rules = [r for r in publish_rules if not r.get("if", "").startswith("$CI_COMMIT_TAG")]
    else:
        # Production: on v* tags, started by hand (protect the environment to choose who can).
        rules = [{"if": SCHEDULED, "when": "never"}, {"if": "$CI_COMMIT_TAG =~ /^v/", "when": "manual"}]
    script = [] if directory == "." else [f'cd "{directory}"']
    if cfg.sign:
        script += [
            "apk add --no-cache cosign",
            # Signed keylessly by this project's pipelines (the publish job).
            f'cosign verify "${IMAGE}@${DIGEST}" --certificate-identity-regexp "^$CI_SERVER_URL/$CI_PROJECT_PATH//" '
            '--certificate-oidc-issuer "$CI_SERVER_URL" > /dev/null',
        ]
    # Without one, helm would try a cluster on localhost.
    script.append(f'[ -n "${{KUBECONFIG:-}}" ] || {{ echo "No KUBECONFIG file variable for the {environment} '
                  'environment: add the cluster\'s kubeconfig (CI/CD variable, type File)."; exit 1; }')
    script.append(helm_upgrade(k8s, environment, settings))
    target: Dict[str, Any] = {"name": environment, "action": "start"}
    address = url(settings, k8s.tls)
    if address:
        target["url"] = address
    return {
        "stage": "deploy",
        "image": {"name": HELM_IMAGE, "entrypoint": [""]},
        "needs": [{"job": _publish_job(delivery), "artifacts": True}],
        "rules": rules,
        "variables": {IMAGE: cfg.image},
        "environment": target,
        "resource_group": f"deploy-{environment}-{delivery.name or 'app'}",
        "interruptible": False,
        "timeout": "15 minutes",
        "script": script,
    }


def _sbom_path(delivery: Delivery) -> str:
    return SBOM_FILE if delivery.directory == "." else f"{delivery.directory}/{SBOM_FILE}"


def _release(deliveries: List[Delivery]) -> Dict[str, Any]:
    """On v* tags, a GitLab release linking to the images' SBOMs, kept with this job's artifacts."""
    links = []
    for d in deliveries:
        url = f"$CI_PROJECT_URL/-/jobs/$CI_JOB_ID/artifacts/raw/{_sbom_path(d)}"
        label = f"{d.name} SBOM (CycloneDX)" if d.name else "SBOM (CycloneDX)"
        links.append({"name": label, "url": url, "link_type": "other"})
    images = ", ".join(d.cfg.image for d in deliveries)
    plural = "s" if len(deliveries) > 1 else ""
    return {
        "stage": "publish",
        "image": GLAB_IMAGE,
        "needs": [{"job": f"{d.name}-publish" if d.name else "publish", "artifacts": True} for d in deliveries],
        "rules": [{"if": "$CI_COMMIT_TAG =~ /^v/"}],
        "script": ['echo "Release $CI_COMMIT_TAG"'],
        "artifacts": {"paths": [_sbom_path(d) for d in deliveries], "expire_in": "never"},
        "release": {
            "tag_name": "$CI_COMMIT_TAG",
            "description": f"Image{plural} {images} ($CI_COMMIT_TAG), with {'their' if plural else 'its'} SBOM "
            "(CycloneDX).",
            "assets": {"links": links},
        },
    }


def plan(project_dir: Path, target: Union[CDConfig, List[Delivery]]) -> List[PlannedFile]:
    return [planned(project_dir, PIPELINE_PATH, render_pipeline(target))]
