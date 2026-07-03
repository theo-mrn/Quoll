from __future__ import annotations

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.java.ci import build_tool
from quoll.languages.java.docker import JavaImage
from quoll.project import Project


class SpringBootImage(JavaImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        return DockerDefaults(
            port=8080,
            command="java org.springframework.boot.loader.launch.JarLauncher",
            build_command=self.build_command(det.package_manager),
        )

    def build_command(self, package_manager: str) -> str:
        tool = build_tool(package_manager)
        return f"{tool} package -DskipTests" if package_manager.startswith("maven") else f"{tool} bootJar"
