from __future__ import annotations

from quoll.languages.base import Detection
from quoll.languages.node.detect import dependencies, package_json
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    if "next" not in dependencies(package_json(project)):
        return False
    # `next build` type-checks, and plain tsc fails without the generated next-env.d.ts.
    det.lint_tools = [t for t in det.lint_tools if t != "tsc"]
    return True
