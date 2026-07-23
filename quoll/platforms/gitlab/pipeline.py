"""Building blocks of GitLab CI pipelines: neutral steps rendered as container jobs, emitted by quoll.yaml_dump."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from quoll import yaml_dump
from quoll.ci.steps import ROOT, Cache, Item, Step

PROJECT_DIR = "$CI_PROJECT_DIR"
# Docker-in-Docker, for the jobs building images.
DOCKER_IMAGE = "docker:29"
DOCKER_SERVICE = "docker:29-dind"


def job(
    stage: str,
    image: str,
    items: Sequence[Item],
    *,
    setup: Sequence[Step] = (),
    caches: Sequence[Cache] = (),
    timeout: int,
    variables: Optional[Dict[str, str]] = None,
    services: Optional[List[Any]] = None,
    parallel: Optional[Dict[str, Any]] = None,
    needs: Optional[List[Any]] = None,
    rules: Optional[List[Dict[str, Any]]] = None,
    artifacts: Optional[Dict[str, Any]] = None,
    directory: str = ".",
) -> Dict[str, Any]:
    """A job running `setup` then `items` in `image`, in the project's `directory`. Steps marked `always` go to
    after_script."""
    # after_script runs in a shell of its own: it moves to the directory too.
    script: List[str] = [] if directory == "." else [f'cd "{directory}"']
    after: List[str] = []
    env: Dict[str, str] = dict(variables or {})
    caches = list(caches)
    for item in [*setup, *items]:
        if isinstance(item, Cache):
            caches.append(item)
            continue
        if item.summary:
            continue
        if not item.run:
            raise ValueError(f"step '{item.name}' has no command to run on GitLab CI")
        env.update(item.env)
        command = item.run
        if item.optional and not item.always:
            # after_script failures never fail the job.
            command = f"{{\n{command}\n}} || echo '{item.name} failed (ignored)'"
        (after if item.always else script).append(command)

    j: Dict[str, Any] = {"stage": stage, "image": image}
    if rules:
        j["rules"] = rules
    if needs is not None:
        j["needs"] = needs
    j["timeout"] = f"{timeout} minutes"
    if parallel:
        j["parallel"] = parallel
    if services:
        j["services"] = services
    root = PROJECT_DIR if directory == "." else f"{PROJECT_DIR}/{directory}"
    for cache in caches:
        env.update({k: v.replace(ROOT, root) for k, v in cache.env.items()})
    if env:
        j["variables"] = env
    if caches:
        j["cache"] = [_cache(c, directory) for c in caches]
    j["script"] = script
    if after:
        j["after_script"] = ([f'cd "{directory}"'] if directory != "." else []) + after
    if artifacts:
        j["artifacts"] = artifacts
    return j


def _cache(c: Cache, directory: str = ".") -> Dict[str, Any]:
    def within(path: str) -> str:
        return path if directory == "." else f"{directory}/{path}"

    # Per job (and matrix entry): a virtualenv built for one interpreter must not leak into another.
    prefix = f"{c.key}-$CI_JOB_NAME_SLUG"
    if c.key_files:
        if len(c.key_files) > 2:
            raise ValueError(f"cache '{c.key}' has {len(c.key_files)} key files; GitLab allows two")
        key: Any = {"files": [within(f) for f in c.key_files], "prefix": prefix}
    else:
        key = prefix
    return {"key": key, "paths": [within(p) for p in c.paths]}


def docker_job(stage: str, script: List[str], *, timeout: int, directory: str = ".", **options: Any) -> Dict[str, Any]:
    """A job with a Docker daemon (Docker-in-Docker, over TLS), building from `directory`."""
    if directory != ".":
        script = [f'cd "{directory}"', *script]
    variables = {"DOCKER_TLS_CERTDIR": "/certs", **options.pop("variables", {})}
    j: Dict[str, Any] = {"stage": stage, "image": DOCKER_IMAGE, "services": [DOCKER_SERVICE]}
    j.update({k: v for k, v in options.items() if k in ("rules", "needs", "interruptible", "resource_group")})
    j["timeout"] = f"{timeout} minutes"
    j["variables"] = variables
    j["script"] = script
    return j


def branch_rule(branch: str) -> Dict[str, str]:
    """Rule matching pushes to `branch`, a name or a GitHub-style pattern (release/*, feature/**)."""
    if not any(c in branch for c in "*?["):
        return {"if": f'$CI_COMMIT_BRANCH == "{branch}"'}
    regex = re.escape(branch).replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    regex = regex.replace("/", r"\/")
    return {"if": f"$CI_COMMIT_BRANCH =~ /^{regex}$/"}


def variable_name(version_key: str) -> str:
    """Matrix variable for a language's version key: python-version -> PYTHON_VERSION."""
    return version_key.upper().replace("-", "_")


def dump(doc: Dict[str, Any]) -> str:
    return yaml_dump.dump(doc, scripts=("script", "before_script", "after_script", "if"))


def registry_cache(project: str) -> str:
    """Shell setting $cache to buildx's options caching layers in the project's registry, under cache:<project>,
    between pipelines (and with the delivery). Without access to the registry (a fork, the registry turned off),
    $cache is empty: the image builds from scratch."""
    return f"""cache=""
if [ -n "${{CI_REGISTRY:-}}" ] && echo "$CI_REGISTRY_PASSWORD" \\
  | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY" >/dev/null 2>&1; then
  ref="$CI_REGISTRY_IMAGE/cache:{project}"
  cache="--cache-from type=registry,ref=$ref"
  cache="$cache --cache-to type=registry,ref=$ref,mode=max,image-manifest=true,ignore-error=true"
fi
docker buildx create --use --driver docker-container >/dev/null"""
