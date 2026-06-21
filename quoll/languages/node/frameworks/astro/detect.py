from __future__ import annotations

from quoll.languages.base import Detection
from quoll.languages.node.detect import dependencies, package_json
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    deps = dependencies(package_json(project))
    if "astro" not in deps:
        return False
    if "@astrojs/check" in deps:
        det.lint_tools = [t for t in det.lint_tools if t != "tsc"] + ["astro-check"]
    return True
