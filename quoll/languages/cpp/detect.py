from __future__ import annotations

import re
from typing import List

from quoll.languages.base import Detection
from quoll.project import Project
from quoll.services import detect_services

# Toolchains, as "<compiler>-<major>" (packages of the Ubuntu 24.04 runners and images).
COMPILER_DEFAULT = "gcc-14"
COMPILERS = ("gcc-14", "clang-18")

# Libraries (CMake packages, vcpkg ports, Conan references) revealing a backing service.
_SERVICE_LIBRARIES = {
    "postgres": ("libpq", "libpqxx", "postgresql", "pq"),
    "mysql": ("libmysqlclient", "mysqlclient", "mariadb-connector-c", "mysql-connector-cpp"),
    "redis": ("hiredis", "redis-plus-plus"),
    "mongodb": ("mongo-cxx-driver", "mongocxx", "mongo-c-driver"),
}
# What makes CTest run tests.
_CTEST = re.compile(
    r"\b(enable_testing|add_test|include\s*\(\s*CTest|gtest_discover_tests|catch_discover_tests)\b", re.I
)


def detect(project: Project) -> Detection:
    det = Detection(version=COMPILER_DEFAULT, matrix_versions=list(COMPILERS))
    meson = project.exists("meson.build") and not project.exists("CMakeLists.txt")
    if meson:
        det.package_manager = "meson"
    elif project.glob_any("conanfile.txt", "conanfile.py"):
        det.package_manager = "conan"
        det.lockfile = "conan.lock" if project.exists("conan.lock") else ""
    elif project.exists("vcpkg.json"):
        det.package_manager = "vcpkg"
    else:
        det.package_manager = "cmake"
    # Dependencies are resolved while configuring the build (FetchContent, Conan, vcpkg, wraps).
    det.install = "meson setup build" if meson else "cmake -S . -B build"

    det.lint_tools = [tool for tool, config in (("clang-format", ".clang-format"), ("clang-tidy", ".clang-tidy"))
                      if project.exists(config)]
    det.lint_tools.append("cppcheck")

    build_files = cmake_files(project) if not meson else project.read_text("meson.build")
    if meson and re.search(r"\btest\s*\(", build_files):
        det.test_runner = "meson"
    elif not meson and _CTEST.search(build_files):
        det.test_runner = "ctest"
    else:
        det.warnings.append("No tests found (enable_testing()/add_test() or meson test()) — the test job is disabled.")
    det.sanitizers = True

    # osv-scanner reads conan.lock; there is no vulnerability database for other C/C++ dependencies.
    det.audit = bool(det.lockfile)
    if not det.audit:
        det.warnings.append("No conan.lock: no dependency audit for C/C++ (Semgrep and the image scan still run).")

    manifests = " ".join([build_files, project.read_text("vcpkg.json"), project.read_text("conanfile.txt"),
                          project.read_text("conanfile.py")]).lower()
    det.services = detect_services(
        [lib for libs in _SERVICE_LIBRARIES.values() for lib in libs if re.search(rf"\b{re.escape(lib)}\b", manifests)],
        _SERVICE_LIBRARIES,
    )
    det.build_command = "meson compile -C build" if meson else "cmake --build build"
    return det


def cmake_files(project: Project) -> str:
    """The root CMakeLists.txt and those of the first-level directories (src/, tests/...)."""
    nested = (p.relative_to(project.root).as_posix() for p in project.glob("*/CMakeLists.txt"))
    paths: List[str] = ["CMakeLists.txt", *nested]
    return "\n".join(project.read_text(p) for p in paths)


def executable(project: Project) -> str:
    """The first executable target that isn't a test."""
    if project.exists("meson.build"):
        pattern, text = r"executable\s*\(\s*['\"]([\w.-]+)['\"]", project.read_text("meson.build")
    else:
        pattern, text = r"add_executable\s*\(\s*([\w.-]+)", cmake_files(project)
    names = [n for n in re.findall(pattern, text, re.I) if not re.search(r"test", n, re.I)]
    return names[0] if names else ""
