from __future__ import annotations

from quoll.languages.base import Detection
from quoll.languages.python.detect import has_dependency
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    return has_dependency(project, "fastapi")
