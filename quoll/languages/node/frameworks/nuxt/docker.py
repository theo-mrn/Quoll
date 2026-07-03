from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.node.docker import NodeImage
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig


class NuxtImage(NodeImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        # Nitro bundles the server and its dependencies into .output.
        return DockerDefaults(
            port=3000,
            command="node .output/server/index.mjs",
            build_command=det.build_command or "npm run build",
            output_dir=".output",
        )

    def build_env(self, cfg: DockerConfig) -> Dict[str, str]:
        return {"NUXT_TELEMETRY_DISABLED": "1"}
