"""Infer the [docker] section from the project, through the language or framework image."""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from quoll import languages
from quoll.ci.detect import Detection
from quoll.docker.config import DockerConfig
from quoll.languages.base import DockerDefaults
from quoll.project import Project


def image_defaults(project_dir: Path, det: Detection) -> DockerDefaults:
    if det.stack is None:
        raise ValueError("cannot build a Docker config without a detected stack")
    image = languages.docker_image(det.stack, det.framework)
    if image is None:
        raise ValueError(f"quoll has no Docker image for {det.stack} yet")
    return image.defaults(Project(project_dir), det)


def default_config(det: Detection, defaults: DockerDefaults) -> Tuple[DockerConfig, List[str]]:
    """The [docker] config (validated) and the warnings to show."""
    cfg = DockerConfig.model_validate(
        {
            "platform": det.platform,
            "stack": det.stack,
            "framework": det.framework,
            "package_manager": det.package_manager,
            "package_manager_version": det.package_manager_version,
            "services": det.services,
            "version": det.version,
            "port": defaults.port,
            "command": defaults.command,
            "build_command": defaults.build_command,
            "output_dir": defaults.output_dir,
            "static": defaults.static,
        }
    )
    return cfg, defaults.warnings
