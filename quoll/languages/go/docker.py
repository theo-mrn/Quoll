from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from quoll.languages.base import Detection, DockerDefaults, DockerImage
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig


class GoImage(DockerImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        package, warnings = _main_package(project)
        return DockerDefaults(
            port=8080,
            command="/app",
            build_command=f'go build -trimpath -ldflags="-s -w" -o /out/app {package}',
            warnings=warnings,
        )

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        # go.mod without a go directive reads as "stable": use the latest Go.
        return {"go_tag": "1" if cfg.version == "stable" else cfg.version, "go_sum": project.exists("go.sum")}

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        return ["bin", "coverage.out", ".env", ".env.*", "!.env.example"]


def _main_package(project: Project):
    """The package to build: the root, cmd/, or the only cmd/<name>/."""
    if project.exists("main.go"):
        return ".", []
    if project.exists("cmd/main.go"):
        return "./cmd", []
    commands = sorted(p.parent.relative_to(project.root).as_posix() for p in project.glob("cmd/*/main.go"))
    if not commands:
        return ".", ["No main package found (main.go or cmd/<name>/main.go) — check docker.build_command."]
    warnings = [] if len(commands) == 1 else [f"Several commands in cmd/ — building ./{commands[0]}."]
    return f"./{commands[0]}", warnings
