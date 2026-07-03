from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from quoll.languages.base import Detection, DockerDefaults, DockerImage
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig

_TEST_MARKERS = ("Microsoft.NET.Test.Sdk", "<IsTestProject>true")


class DotnetImage(DockerImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        app = _app_project(project)
        if app is None:
            return DockerDefaults(port=8080, warnings=["No application project found — set docker.build_command."])
        rel = app.relative_to(project.root).as_posix()
        assembly = re.search(r"<AssemblyName>([^<]+)</AssemblyName>", app.read_text())
        name = assembly.group(1) if assembly else app.stem
        return DockerDefaults(
            port=8080,
            command=f"dotnet {name}.dll",
            build_command=f"dotnet publish {rel} --configuration Release --output /out",
        )

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        published = re.search(r"dotnet publish (\S+)", cfg.build_command)
        csproj = project.read_text(published.group(1)) if published else ""
        return {"web": 'Sdk="Microsoft.NET.Sdk.Web"' in csproj}

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        return ["**/bin", "**/obj", "**/TestResults", ".vs", "*.user", ".env", ".env.*", "!.env.example"]


def _app_project(project: Project) -> Optional[Path]:
    """The project to publish: a web project first, then any non-test project, shallowest first."""
    candidates = [
        p
        for p in project.glob("*.csproj", "*/*.csproj", "*/*/*.csproj", "*.fsproj", "*/*.fsproj", "*/*/*.fsproj")
        if not any(marker in p.read_text() for marker in _TEST_MARKERS)
    ]
    candidates.sort(key=lambda p: ("Microsoft.NET.Sdk.Web" not in p.read_text(), len(p.parts)))
    return candidates[0] if candidates else None
