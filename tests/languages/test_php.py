from __future__ import annotations

from quoll.ci.detect import detect
from tests.helpers import runs, steps, workflow
from tests.samples import LARAVEL, PHP_COMPOSER, SYMFONY


def test_composer(make_project) -> None:
    det = detect(make_project(PHP_COMPOSER))
    assert det.stack == "php"
    assert det.matrix_versions == ["8.3", "8.4", "8.5"]
    assert det.version == "8.5"
    assert det.lint_tools == ["php-cs-fixer", "phpstan"]
    assert det.test_runner == "phpunit"
    doc = workflow(make_project, PHP_COMPOSER)
    assert steps(doc, "test")[1]["with"]["coverage"] == "pcov"
    assert "vendor/bin/phpstan analyse --no-progress --error-format=github" in runs(doc, "lint")
    assert 'simplexml_load_file("coverage.xml")' in runs(doc, "test")
    audit = runs(doc, "audit")
    assert "composer audit --locked --no-dev" in audit
    assert "nothing to audit" in audit  # composer.json requiring only php: audit would exit 1


def test_pest_threshold(make_project) -> None:
    files = {"composer.json": {"require-dev": {"pestphp/pest": "^3"}}, "composer.lock": "{}"}
    assert detect(make_project(files)).test_runner == "pest"
    assert "vendor/bin/pest --coverage --min=80" in runs(workflow(make_project, files), "test")


def test_symfony(make_project) -> None:
    det = detect(make_project(SYMFONY))
    assert det.framework == "symfony"
    assert det.lint_tools == ["symfony-container", "symfony-yaml", "symfony-twig"]
    assert "php bin/console lint:container" in runs(workflow(make_project, SYMFONY), "lint")


def test_laravel(make_project) -> None:
    det = detect(make_project(LARAVEL))
    assert det.framework == "laravel"
    assert det.lint_tools == ["pint"]
    assert det.test_runner == "artisan"
    test = runs(workflow(make_project, LARAVEL), "test")
    assert "php artisan key:generate" in test
    assert "php artisan test --coverage --min=80" in test


def test_symfony_needs_its_console(make_project) -> None:
    files = {k: v for k, v in SYMFONY.items() if k != "bin/console"}
    assert detect(make_project(files)).framework == ""
