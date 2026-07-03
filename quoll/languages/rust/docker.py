from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from quoll.languages.base import Detection, DockerDefaults, DockerImage
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig


class RustImage(DockerImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        build = "cargo build --release --locked" if project.exists("Cargo.lock") else "cargo build --release"
        warnings = [] if binary_name(project) else ["No binary target in Cargo.toml — check docker.build_command."]
        return DockerDefaults(port=8080, command="/app", build_command=build, warnings=warnings)

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        tag = "1" if cfg.version in ("stable", "") else cfg.version
        return {
            "rust_tag": tag,
            "binary": binary_name(project) or project.name,
            # openssl-sys links against the system OpenSSL.
            "openssl": "openssl-sys" in project.read_text("Cargo.lock"),
        }

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        return ["target", ".env", ".env.*", "!.env.example"]


def binary_name(project: Project) -> str:
    cargo = project.read_toml("Cargo.toml")
    bins = cargo.get("bin", [])
    if bins and isinstance(bins, list) and bins[0].get("name"):
        return bins[0]["name"]
    if project.exists("src/main.rs"):
        return cargo.get("package", {}).get("name", "")
    return ""
