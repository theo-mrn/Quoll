from __future__ import annotations

from quoll.languages.base import Detection
from quoll.languages.php.detect import composer_packages
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    packages = composer_packages(project)
    if "symfony/framework-bundle" not in packages or not project.exists("bin/console"):
        return False
    det.lint_tools.append("symfony-container")
    if project.is_dir("config"):
        det.lint_tools.append("symfony-yaml")
    if "symfony/twig-bundle" in packages and project.is_dir("templates"):
        det.lint_tools.append("symfony-twig")
    return True
