from __future__ import annotations

import re
from typing import List

from quoll.languages.base import Detection
from quoll.languages.java.ci import build_tool
from quoll.project import Project
from quoll.services import detect_services

JAVA_DEFAULT = "21"
JAVA_LTS = ("17", "21", "25")

_VERSION_PATTERNS = (
    r"<java\.version>\s*(?:1\.)?(\d+)",
    r"<maven\.compiler\.release>\s*(\d+)",
    r"<maven\.compiler\.source>\s*(?:1\.)?(\d+)",
    r"<release>\s*(\d+)\s*</release>",
    r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)",
    r"JavaVersion\.VERSION_(?:1_)?(\d+)",
    r"jvmToolchain\(\s*(\d+)\s*\)",
    r"sourceCompatibility\s*=\s*['\"]?(?:1\.)?(\d+)",
)

# Artifacts revealing a backing service.
_SERVICE_ARTIFACTS = {
    "postgres": ("org.postgresql", "postgresql:postgresql"),
    "mysql": ("mysql-connector", "com.mysql"),
    "redis": ("spring-boot-starter-data-redis", "jedis", "lettuce-core", "redisson"),
    "mongodb": ("mongodb-driver", "spring-boot-starter-data-mongodb"),
}
# Enabled when their plugin name appears in a build file.
_LINT_TOOLS = ("spotless", "checkstyle", "ktlint", "detekt", "spotbugs", "pmd")


def detect(project: Project) -> Detection:
    det = Detection(install="", lockfile="")
    if project.exists("pom.xml"):
        det.package_manager = "maven-wrapper" if project.exists("mvnw") else "maven"
    else:
        det.package_manager = "gradle-wrapper" if project.exists("gradlew") else "gradle"
    if det.package_manager in ("maven", "gradle"):
        wrapper = "mvnw" if det.package_manager == "maven" else "gradlew"
        det.warnings.append(f"No ./{wrapper} found — the CI uses the runner's {det.package_manager}.")

    build_files = build_text(project)
    if project.exists(".java-version"):
        det.version_file = ".java-version"
        det.version = project.read_text(".java-version").strip().split(".")[0] or JAVA_DEFAULT
    else:
        det.version = next(
            (m.group(1) for p in _VERSION_PATTERNS for m in [re.search(p, build_files)] if m), JAVA_DEFAULT
        )
    low = int(det.version) if det.version.isdigit() else 0
    det.matrix_versions = [v for v in JAVA_LTS if int(v) >= low] or [det.version]

    det.lint_tools = [tool for tool in _LINT_TOOLS if tool in build_files]
    if project.glob_any("src/test", "*/src/test"):
        det.test_runner = "junit"
    else:
        det.warnings.append("No src/test directory found — the test job is disabled.")

    found = [a for artifacts in _SERVICE_ARTIFACTS.values() for a in artifacts if a in build_files]
    det.services = detect_services(found, _SERVICE_ARTIFACTS)

    tool = build_tool(det.package_manager)
    det.build_command = f"{tool} package -DskipTests" if det.package_manager.startswith("maven") else f"{tool} assemble"
    return det


def build_text(project: Project) -> str:
    """Contents of the root and module build files."""
    names: List[str] = ["pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"]
    files = [project.read_text(n) for n in names]
    files += [p.read_text() for p in project.glob("*/pom.xml", "*/build.gradle", "*/build.gradle.kts")]
    files.append(project.read_text("gradle/libs.versions.toml"))
    return "\n".join(files)
