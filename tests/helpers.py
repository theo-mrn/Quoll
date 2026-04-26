"""Helpers to generate workflows from sample projects and inspect them."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from quoll.ci.config import CIConfig
from quoll.ci.detect import default_config, detect
from quoll.platforms.github import ci as render
from quoll.platforms.github.actions import PINS

# actionlint-py and check-jsonschema (dev dependencies) install their binaries next to the interpreter.
ACTIONLINT = (
    os.environ.get("ACTIONLINT")
    or shutil.which("actionlint")
    or shutil.which("actionlint", path=str(Path(sys.executable).parent))
)
CHECK_JSONSCHEMA = shutil.which("check-jsonschema", path=str(Path(sys.executable).parent)) or shutil.which(
    "check-jsonschema"
)

_UNPIN = {f"{ref.split('@')[0]}@{sha}": ref for ref, sha in PINS.items()}


def config(make_project, files, platform: str = "github", **overrides) -> CIConfig:
    """Detected config for `files` on `platform`; `section__field=value` or `field=value` overrides."""
    det = detect(make_project(files))
    det.platform = platform
    data = default_config(det).model_dump()
    for key, value in overrides.items():
        section, _, field = key.partition("__")
        if field:
            data[section][field] = value
        else:
            data[section] = value
    return CIConfig.model_validate(data)


def workflow(make_project, files, **overrides) -> dict:
    return load(render.render_workflow(config(make_project, files, **overrides)))


def pipeline(make_project, files, **overrides) -> dict:
    """The .gitlab-ci.yml of `files`, parsed."""
    from quoll.platforms.gitlab.ci import render_pipeline

    return yaml.safe_load(render_pipeline(config(make_project, files, platform="gitlab", **overrides)))


def script(doc: dict, job: str) -> str:
    return "\n".join(doc[job]["script"])


def load(text: str) -> dict:
    """A workflow, with pinned actions (owner/repo@<sha>) read back as owner/repo@<version>."""
    doc = yaml.safe_load(text)
    doc["on"] = doc.pop(True)  # YAML 1.1 reads the `on` key as a boolean
    for job in doc.get("jobs", {}).values():
        for s in job.get("steps", []):
            if "uses" in s:
                s["uses"] = _UNPIN.get(s["uses"], s["uses"])
    return doc


def steps(doc: dict, job: str) -> list:
    return doc["jobs"][job]["steps"]


def runs(doc: dict, job: str) -> str:
    return "\n".join(s.get("run", "") for s in steps(doc, job))


def uses(doc: dict, job: str) -> list:
    return [s["uses"] for s in steps(doc, job) if "uses" in s]


def actionlint(tmp_path: Path, text: str) -> None:
    if not ACTIONLINT:
        pytest.skip("actionlint not installed")
    path = tmp_path / "ci.yml"
    path.write_text(text)
    result = subprocess.run([ACTIONLINT, "-no-color", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def dockerfile(make_project, files, **overrides) -> str:
    """Dockerfile rendered from the detected [docker] config; `field=value` overrides it."""
    from quoll.docker.detect import default_config as docker_default_config
    from quoll.docker.detect import image_defaults
    from quoll.docker.render import render_dockerfile

    root = make_project(files)
    det = detect(root)
    defaults = image_defaults(root, det)
    defaults.command = defaults.command or "run-app"
    for key, value in overrides.items():
        setattr(defaults, key, value)
    cfg, _ = docker_default_config(det, defaults)
    return render_dockerfile(root, cfg)


def action_lint(tmp_path: Path, text: str) -> None:
    """Validate an action.yml against GitHub's action metadata schema."""
    if not CHECK_JSONSCHEMA:
        pytest.skip("check-jsonschema not installed")
    path = tmp_path / "action.yml"
    path.write_text(text)
    result = subprocess.run(
        [CHECK_JSONSCHEMA, "--builtin-schema", "vendor.github-actions", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def gitlab_lint(tmp_path: Path, text: str, name: str = ".gitlab-ci.yml") -> None:
    """Validate against GitLab's CI schema (vendored by check-jsonschema: works offline)."""
    if not CHECK_JSONSCHEMA:
        pytest.skip("check-jsonschema not installed")
    path = tmp_path / name.replace("/", "_")
    path.write_text(text)
    result = subprocess.run(
        [CHECK_JSONSCHEMA, "--builtin-schema", "vendor.gitlab-ci", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
