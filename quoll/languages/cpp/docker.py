from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from quoll.languages.base import Detection, DockerDefaults, DockerImage
from quoll.languages.cpp.detect import executable
from quoll.project import Project

if TYPE_CHECKING:
    from quoll.docker.config import DockerConfig


# Build tools on top of the gcc image.
_PACKAGES = {
    "cmake": ("cmake", "ninja-build"),
    "conan": ("cmake", "ninja-build", "pipx"),
    "vcpkg": ("cmake", "ninja-build", "curl", "zip", "unzip", "tar", "pkg-config"),
    "meson": ("meson", "ninja-build"),
}


class CppImage(DockerImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        warnings = ["C/C++ programs don't say which port they listen on — check docker.port."]
        target = executable(project)
        if not target:
            warnings.append("No executable target found (add_executable / executable()) — check docker.command.")
        if det.package_manager == "meson":
            build = "meson setup build --buildtype=release && meson compile -C build"
        else:
            build = "cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build"
        return DockerDefaults(port=8080, command="/app", build_command=build, warnings=warnings)

    def context(self, project: Project, cfg: DockerConfig) -> Dict[str, Any]:
        compiler, _, major = cfg.version.partition("-")
        return {
            # The official gcc image builds both C and C++; clang projects build with the same major of GCC's
            # libstdc++ either way.
            "gcc_tag": major if compiler == "gcc" and major else "14",
            "target": executable(project) or project.name,
            "packages": " ".join(_PACKAGES[cfg.package_manager]),
            "conan": cfg.package_manager == "conan",
            "vcpkg": cfg.package_manager == "vcpkg",
        }

    def dockerignore(self, cfg: DockerConfig) -> List[str]:
        return ["build", "build-*", "cmake-build-*", "out", ".env", ".env.*", "!.env.example"]
