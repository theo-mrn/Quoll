from __future__ import annotations

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.node.detect import dependencies, package_json
from quoll.languages.node.docker import NodeImage
from quoll.project import Project


class AstroImage(NodeImage):
    # Astro builds one HTML file per page and a 404.html.
    spa = False

    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        build = det.build_command or "npm run build"
        if "@astrojs/node" in dependencies(package_json(project)):
            return DockerDefaults(port=4321, command="node ./dist/server/entry.mjs", build_command=build)
        return DockerDefaults(port=8080, build_command=build, output_dir="dist", static=True)
