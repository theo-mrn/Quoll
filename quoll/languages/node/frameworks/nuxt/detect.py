from __future__ import annotations

from quoll.languages.base import SCRIPT_PREFIX, Detection
from quoll.languages.node.detect import dependencies, package_json
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    deps = dependencies(package_json(project))
    if "nuxt" not in deps:
        return False
    had_tsc = "tsc" in det.lint_tools
    det.lint_tools = [t for t in det.lint_tools if t != "tsc"]
    has_typecheck_script = any(t.startswith(f"{SCRIPT_PREFIX}type") for t in det.lint_tools)
    if (had_tsc or "vue-tsc" in deps) and not has_typecheck_script:
        det.lint_tools.append("nuxt-typecheck")
    return True
