from __future__ import annotations

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.node.docker import NodeImage
from quoll.project import Project


class NestjsImage(NodeImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        return DockerDefaults(port=3000, command="node dist/main", build_command=det.build_command or "npm run build")
