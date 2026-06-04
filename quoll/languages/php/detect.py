from __future__ import annotations

import re
from typing import Dict

from quoll.languages.base import Detection
from quoll.project import Project
from quoll.services import detect_services

PHP_SUPPORTED = ("8.2", "8.3", "8.4", "8.5")

# composer package: lint tool
_LINT_PACKAGES = {
    "friendsofphp/php-cs-fixer": "php-cs-fixer",
    "squizlabs/php_codesniffer": "phpcs",
    "laravel/pint": "pint",
    "phpstan/phpstan": "phpstan",
    "vimeo/psalm": "psalm",
    "rector/rector": "rector",
}


# Packages and extensions revealing a backing service.
_SERVICE_PACKAGES = {
    "postgres": ("ext-pdo_pgsql", "ext-pgsql"),
    "mysql": ("ext-pdo_mysql", "ext-mysqli"),
    "redis": ("predis/predis", "ext-redis", "snc/redis-bundle"),
    "mongodb": ("mongodb/mongodb", "ext-mongodb", "doctrine/mongodb-odm"),
}
# Database settings in Symfony's .env / Laravel's .env.example.
_ENV_DATABASES = {
    "ext-pdo_pgsql": r"^(DATABASE_URL=\W*postgres|DB_CONNECTION=pgsql)",
    "ext-pdo_mysql": r"^(DATABASE_URL=\W*(mysql|mariadb)|DB_CONNECTION=(mysql|mariadb))",
}


def detect(project: Project) -> Detection:
    det = Detection(package_manager="composer", install="composer install --no-interaction --no-progress --prefer-dist")
    det.lockfile = "composer.lock" if project.exists("composer.lock") else ""
    if not det.lockfile:
        det.warnings.append("No composer.lock found — commit it for reproducible builds.")

    packages = composer_packages(project)
    m = re.search(r"(\d+)\.(\d+)", packages.get("php", ""))
    low = f"{m.group(1)}.{m.group(2)}" if m else PHP_SUPPORTED[0]
    det.matrix_versions = [v for v in PHP_SUPPORTED if _key(v) >= _key(low)] or [PHP_SUPPORTED[-1]]
    if project.exists(".php-version"):
        det.version_file = ".php-version"
        det.version = project.read_text(".php-version").strip()
    else:
        det.version = det.matrix_versions[-1]

    det.lint_tools = [tool for package, tool in _LINT_PACKAGES.items() if package in packages]
    if "pestphp/pest" in packages:
        det.test_runner = "pest"
    elif "phpunit/phpunit" in packages or "symfony/phpunit-bridge" in packages:
        det.test_runner = "phpunit"
    else:
        det.warnings.append("No test framework found (phpunit/phpunit or pestphp/pest) — the test job is disabled.")
    env = project.read_text(".env") + project.read_text(".env.example")
    implied = [ext for ext, pattern in _ENV_DATABASES.items() if re.search(pattern, env, re.M)]
    det.services = detect_services([*packages, *implied], _SERVICE_PACKAGES)
    return det


def composer_packages(project: Project) -> Dict[str, str]:
    """`require` and `require-dev` of composer.json, merged."""
    composer = project.read_json("composer.json")
    if not isinstance(composer, dict):
        return {}
    return {**(composer.get("require") or {}), **(composer.get("require-dev") or {})}


def _key(version: str) -> tuple:
    return tuple(int(p) for p in version.split("."))
