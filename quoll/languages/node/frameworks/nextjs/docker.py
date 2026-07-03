from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.node.docker import NodeImage
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig

STANDALONE_DIR = ".next/standalone"
_CONFIGS = ("next.config.js", "next.config.mjs", "next.config.ts")


class NextjsImage(NodeImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        build = det.build_command or "npm run build"
        if any("standalone" in project.read_text(c) for c in _CONFIGS):
            return DockerDefaults(port=3000, command="node server.js", build_command=build, output_dir=STANDALONE_DIR)
        return DockerDefaults(
            port=3000,
            command="next start",
            build_command=build,
            warnings=['Set `output: "standalone"` in next.config for a much smaller image.'],
        )

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        standalone = cfg.output_dir == STANDALONE_DIR
        return {**super().context(project, cfg), "standalone": standalone, "public": project.is_dir("public")}

    def writable_paths(self, cfg: DockerConfig) -> Optional[List[str]]:
        # The image optimization and ISR cache.
        return ["/tmp", "/app/.next/cache"]

    def build_env(self, cfg: DockerConfig) -> Dict[str, str]:
        return {"NEXT_TELEMETRY_DISABLED": "1"}

    def env(self, cfg: DockerConfig) -> Dict[str, str]:
        # The standalone server listens on HOSTNAME.
        return {"HOSTNAME": "0.0.0.0", "NEXT_TELEMETRY_DISABLED": "1"}
