"""The [docker] section of quoll.toml — the single source of truth for the generated Dockerfile."""
from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar, Dict, Tuple

from pydantic import Field, model_validator

from quoll import languages
from quoll.config.quoll_toml import CONFIG_FILE, ConfigError, ProjectConfig, load_section, save_section
from quoll.languages.base import DockerImage

__all__ = ["CONFIG_FILE", "ConfigError", "DockerConfig", "load_config", "save_config"]


class DockerConfig(ProjectConfig):
    # Runtime version of the base image, e.g. "3.13", "24", "1.25", "21".
    version: str
    port: int = Field(default=8000, ge=1, le=65535)
    # What the container runs. Not needed for static sites or images that ship their own server.
    command: str = ""
    # Run in the build stage, e.g. "npm run build". Empty = nothing to build.
    build_command: str = ""
    # Build output the image ships: the site when `static`, otherwise a self-contained server bundle.
    output_dir: str = ""
    # Serve `output_dir` with nginx instead of running a server.
    static: bool = False
    # Static sites: path prefixes nginx forwards to an API, each to the URL held by an environment variable, e.g.
    # {"/api/" = "BACK_URL"} (a workspace's compose.yaml sets <NAME>_URL for each of its projects).
    proxy: Dict[str, str] = {}

    omit_when_empty: ClassVar[Tuple[str, ...]] = ("proxy",)

    @model_validator(mode="after")
    def _check_docker(self) -> "DockerConfig":
        if self.static and not self.output_dir:
            raise ValueError("output_dir is required when static is true")
        if self.proxy and not self.static:
            raise ValueError("proxy is for static sites (static = true), served by nginx")
        for path, variable in self.proxy.items():
            if not path.startswith("/") or not path.endswith("/"):
                raise ValueError(f"proxy: {path!r} should start and end with /, e.g. /api/")
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", variable):
                raise ValueError(f"proxy: {variable!r} should name an environment variable, e.g. BACK_URL")
        if not self.static and not self.command and self.image.requires_command:
            raise ValueError(f"command is required: what should the {self.target} container run?")
        return self

    @property
    def image(self) -> DockerImage:
        image = languages.docker_image(self.stack, self.framework)
        if image is None:
            raise ValueError(f"quoll has no Docker image for {self.target} yet")
        return image


def load_config(project_dir: Path) -> DockerConfig:
    return load_section(project_dir, "docker", DockerConfig)


def save_config(project_dir: Path, config: DockerConfig) -> Path:
    """Write [project] and [docker], preserving any other section already in quoll.toml."""
    return save_section(project_dir, "docker", config)
