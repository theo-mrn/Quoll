from __future__ import annotations

from quoll.languages.base import Detection
from quoll.languages.php.detect import composer_packages
from quoll.project import Project


def detect(project: Project, det: Detection) -> bool:
    if "laravel/framework" not in composer_packages(project) or not project.exists("artisan"):
        return False
    # `php artisan test` drives PHPUnit or Pest, whichever the project uses.
    det.test_runner = "artisan"
    return True
