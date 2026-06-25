from __future__ import annotations

from quoll.languages.base import Detection
from quoll.languages.ruby.detect import has_gem
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    if not has_gem(project, "rails") or not project.exists("bin/rails"):
        return False
    if has_gem(project, "brakeman"):
        det.lint_tools.append("brakeman")
    if det.test_runner:
        det.test_runner = "rails-rspec" if det.test_runner == "rspec" else "rails"
    return True
