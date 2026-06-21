from __future__ import annotations

from quoll.languages.base import Detection
from quoll.languages.node.detect import dependencies, package_json
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    return "@nestjs/core" in dependencies(package_json(project))
