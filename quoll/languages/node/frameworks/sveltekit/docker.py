from __future__ import annotations

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.node.detect import dependencies, package_json
from quoll.languages.node.docker import NodeImage
from quoll.project import Project


class SvelteKitImage(NodeImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        deps = dependencies(package_json(project))
        build = det.build_command or "npm run build"
        if "@sveltejs/adapter-static" in deps:
            return DockerDefaults(port=8080, build_command=build, output_dir="build", static=True)
        warnings = []
        if "@sveltejs/adapter-node" not in deps:
            warnings.append("Use @sveltejs/adapter-node (or adapter-static) in svelte.config.js to run in a container.")
        return DockerDefaults(port=3000, command="node build", build_command=build, warnings=warnings)
