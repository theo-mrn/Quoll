"""Docker image for Vue: a static SPA built with Vite and served by nginx."""
from __future__ import annotations

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.node.docker import NodeImage
from quoll.project import Project


class VueImage(NodeImage):
    spa = True

    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        build = det.build_command or "npm run build"
        return DockerDefaults(port=8080, build_command=build, output_dir="dist", static=True)
