from __future__ import annotations

from quoll.languages.base import SCRIPT_PREFIX, Detection
from quoll.languages.node.detect import dependencies, package_json, scripts_of
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    pkg = package_json(project)
    if "@sveltejs/kit" not in dependencies(pkg):
        return False
    det.lint_tools = [t for t in det.lint_tools if t != "tsc"]
    # The SvelteKit template ships a `check` script running svelte-kit sync + svelte-check.
    if "check" in scripts_of(pkg):
        det.lint_tools.append(f"{SCRIPT_PREFIX}check")
    elif "svelte-check" in dependencies(pkg):
        det.lint_tools.append("svelte-check")
    return True
