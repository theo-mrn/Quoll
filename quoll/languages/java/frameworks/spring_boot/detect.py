from __future__ import annotations

from quoll.languages.base import Detection
from quoll.languages.java.detect import build_text
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    return "spring-boot" in build_text(project)
