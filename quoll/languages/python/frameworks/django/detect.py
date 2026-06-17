from __future__ import annotations

from quoll.languages.base import Detection
from quoll.languages.python.detect import has_dependency
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    if not has_dependency(project, "django") or not project.exists("manage.py"):
        return False
    det.lint_tools += ["django-check", "django-migrations"]
    # Apps sit next to the settings package, so measure the whole project.
    det.source_dir = "."
    # pytest-django brings pytest; otherwise manage.py finds the tests.py of each app.
    det.test_runner = "pytest" if has_dependency(project, "pytest-django") else "django"
    det.warnings = [w for w in det.warnings if not w.startswith("No tests found")]
    return True
