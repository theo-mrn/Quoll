from __future__ import annotations

from quoll.languages.base import Detection
from quoll.languages.node.detect import dependencies, package_json, scripts_of
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    pkg = package_json(project)
    deps = dependencies(pkg)
    if "@angular/core" not in deps:
        return False
    # `ng build` type-checks, and Angular's solution-style tsconfig.json makes plain tsc a no-op.
    det.lint_tools = [t for t in det.lint_tools if t != "tsc"]
    if "ng test" in scripts_of(pkg).get("test", ""):
        det.test_runner = "angular-karma" if "karma" in deps else "angular"
        # Coverage thresholds live in karma.conf.js / angular.json.
        det.coverage = False
        det.warnings = [w for w in det.warnings if "vitest coverage" not in w]
    return True
