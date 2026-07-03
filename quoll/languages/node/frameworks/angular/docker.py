from __future__ import annotations

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.node.detect import dependencies, package_json
from quoll.languages.node.docker import NodeImage
from quoll.project import Project


class AngularImage(NodeImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        build = det.build_command or "npm run build"
        output, application_builder, ssr = _build_target(project)
        if ssr and "@angular/ssr" in dependencies(package_json(project)):
            return DockerDefaults(port=4000, command=f"node {output}/server/server.mjs", build_command=build)
        # The application builder writes the browser bundle to <outputPath>/browser.
        site = f"{output}/browser" if application_builder else output
        return DockerDefaults(port=8080, build_command=build, output_dir=site, static=True)


def _build_target(project: Project):
    """(outputPath, uses the application builder, has SSR) of the first project in angular.json."""
    workspace = project.read_json("angular.json")
    projects = workspace.get("projects", {}) if isinstance(workspace, dict) else {}
    name, config = next(iter(projects.items()), (project.name, {}))
    build = config.get("architect", {}).get("build", {})
    options = build.get("options", {})
    output = options.get("outputPath", f"dist/{name}")
    if isinstance(output, dict):
        output = output.get("base", f"dist/{name}")
    application_builder = str(build.get("builder", ":application")).endswith(":application")
    return output, application_builder, bool(options.get("ssr") or options.get("server"))
