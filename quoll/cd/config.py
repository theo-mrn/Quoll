"""The [cd] section of quoll.toml — the single source of truth for the generated delivery workflow."""
from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field, model_validator

from quoll.config.quoll_toml import CONFIG_FILE, ConfigError, PlatformField, Section, load_section, save_section
from quoll.platforms import get as get_platform

__all__ = ["CONFIG_FILE", "CDConfig", "ConfigError", "load_config", "save_config"]

SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")


class CDConfig(Section, PlatformField):
    shared_fields = ("platform",)

    # The platform's own registry, authenticated with the pipeline's token (no secret to set):
    #   ghcr (GitHub Container Registry) on GitHub, gitlab (the project's container registry) on GitLab.
    # dockerhub: Docker Hub, with the DOCKERHUB_USERNAME and DOCKERHUB_TOKEN secrets / CI/CD variables.
    registry: str = ""
    # Full image name, e.g. "ghcr.io/acme/api", "registry.gitlab.com/acme/api" or "acme/api" on Docker Hub.
    image: str
    # Every push to these branches publishes :<branch>, :sha-<sha> and :latest for the default branch.
    branches: List[str] = Field(default_factory=lambda: ["main"])
    # Git tags v1.2.3 publish :1.2.3 and :1.2.
    release_tags: bool = True
    platforms: List[str] = Field(default_factory=lambda: ["linux/amd64"])
    # Trivy scans the image before it is pushed; findings of these severities block the push.
    scan: bool = True
    severity: List[str] = Field(default_factory=lambda: ["CRITICAL", "HIGH"])
    # Only block on vulnerabilities that have a fix available.
    ignore_unfixed: bool = True
    # SBOM (CycloneDX) of the published image: a pipeline artifact, attached to the v* releases.
    sbom: bool = True
    # Sign the image and its SBOM with Sigstore: GitHub artifact attestations (public repositories, or GitHub
    # Enterprise Cloud for private ones) / cosign keyless on gitlab.com. Verify with `gh attestation verify` / `cosign
    # verify`.
    sign: bool = True

    @model_validator(mode="after")
    def _check(self) -> "CDConfig":
        registries = get_platform(self.platform).registries
        if not self.registry:
            self.registry = registries[0]
        if self.registry not in registries:
            raise ValueError(
                f"unknown registry '{self.registry}' for {self.platform} (expected one of: {', '.join(registries)})"
            )
        if self.registry == "ghcr" and not self.image.startswith("ghcr.io/"):
            raise ValueError("image must start with ghcr.io/ when registry is ghcr")
        if self.registry == "gitlab" and "/" not in self.image.split("/", 1)[-1]:
            raise ValueError("image must include the registry host, e.g. registry.gitlab.com/group/project")
        if self.image != self.image.lower():
            raise ValueError("image names must be lowercase")
        unknown = [s for s in self.severity if s not in SEVERITIES]
        if unknown:
            raise ValueError(f"unknown severity '{unknown[0]}' (expected some of: {', '.join(SEVERITIES)})")
        if self.scan and not self.severity:
            raise ValueError("severity must list at least one level when scan is true")
        if not self.branches and not self.release_tags:
            raise ValueError("nothing would publish the image: set branches or release_tags")
        if not self.platforms:
            raise ValueError("platforms must contain at least one platform")
        return self


def load_config(project_dir: Path) -> CDConfig:
    return load_section(project_dir, "cd", CDConfig)


def save_config(project_dir: Path, config: CDConfig) -> Path:
    return save_section(project_dir, "cd", config)
