from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from quoll.languages.base import Detection, DockerDefaults, DockerImage
from quoll.languages.java.ci import build_tool
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig


class JavaImage(DockerImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        return DockerDefaults(
            port=8080,
            command="java -jar /app/app.jar",
            build_command=self.build_command(det.package_manager),
            warnings=["The image runs the built jar: make sure it is executable (Main-Class in its manifest)."],
        )

    def build_command(self, package_manager: str) -> str:
        tool = build_tool(package_manager)
        return f"{tool} package -DskipTests" if package_manager.startswith("maven") else f"{tool} assemble"

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        pm, version = cfg.package_manager, cfg.version
        maven = pm.startswith("maven")
        # Wrappers fetch their own Maven/Gradle; otherwise build in the official Maven/Gradle image.
        build_image = {
            "maven-wrapper": f"eclipse-temurin:{version}-jdk",
            "gradle-wrapper": f"eclipse-temurin:{version}-jdk",
            "maven": f"maven:3-eclipse-temurin-{version}",
            "gradle": f"gradle:jdk{version}",
        }[pm]
        return {
            "build_image": build_image,
            "cache": "/root/.m2" if maven else ("/home/gradle/.gradle" if pm == "gradle" else "/root/.gradle"),
            "jar_dir": "target" if maven else "build/libs",
            # Wrappers committed from Windows or unzipped lose their executable bit.
            "wrapper": {"maven-wrapper": "mvnw", "gradle-wrapper": "gradlew"}.get(pm, ""),
        }

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        return ["target", "build", ".gradle", "**/*.class", ".env", ".env.*", "!.env.example"]
