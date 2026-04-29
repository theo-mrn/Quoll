from __future__ import annotations

from quoll.ci.detect import default_config, detect
from quoll.platforms.github import ci as render
from tests.helpers import actionlint, config, load, runs, steps, uses, workflow
from tests.samples import DJANGO, FASTAPI, PYTHON_PIP, PYTHON_POETRY, PYTHON_UV

# --------------------------------------------------------------------------- detection


def test_uv(make_project) -> None:
    det = detect(make_project(PYTHON_UV))
    assert det.stack == "python"
    assert det.package_manager == "uv"
    assert det.install == "uv sync --locked --all-extras"
    assert det.version == "3.14"
    assert det.matrix_versions == ["3.11", "3.12", "3.13", "3.14"]
    assert det.source_dir == "src"
    assert det.lint_tools == ["ruff", "ruff-format", "mypy"]
    assert det.test_runner == "pytest"
    assert det.build_command == "uv build"
    assert det.warnings == []


def test_uv_without_lockfile_warns(make_project) -> None:
    files = {k: v for k, v in PYTHON_UV.items() if k != "uv.lock"}
    files["pyproject.toml"] += "\n[tool.uv]\npackage = true\n"
    det = detect(make_project(files))
    assert det.package_manager == "uv"
    assert det.install == "uv sync --all-extras"
    assert any("uv.lock" in w for w in det.warnings)


def test_pip(make_project) -> None:
    det = detect(make_project(PYTHON_PIP))
    assert det.package_manager == "pip"
    assert det.install == (
        "python -m pip install --upgrade pip\npip install -r requirements.txt -r requirements-dev.txt"
    )
    assert det.version_file == ".python-version"
    assert det.version == "3.12"
    assert det.lint_tools == ["flake8"]
    assert det.source_dir == "."
    assert det.build_command == ""


def test_pip_installable_pyproject_with_extras(make_project) -> None:
    pyproject = """
[project]
name = "lib"
[project.optional-dependencies]
dev = ["pytest"]
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""
    det = detect(make_project({"pyproject.toml": pyproject}))
    assert det.install.endswith('pip install -e ".[dev]"')
    assert det.build_command == "pip install build\npython -m build"


def test_poetry(make_project) -> None:
    det = detect(make_project(PYTHON_POETRY))
    assert det.package_manager == "poetry"
    assert det.matrix_versions[0] == "3.10"
    assert det.source_dir == "svc"
    assert det.lint_tools == ["ruff"]  # default when nothing is configured
    assert det.test_runner == "pytest"


def test_single_package_is_the_source_dir(make_project) -> None:
    det = detect(make_project({"requirements.txt": "", "mylib/__init__.py": "", "tests/__init__.py": ""}))
    assert det.source_dir == "mylib"


def test_without_tests_disables_test_job(make_project) -> None:
    det = detect(make_project({"requirements.txt": "flask\n"}))
    assert det.test_runner == ""
    assert not default_config(det).test.enabled


def test_invalid_pyproject_warns(make_project) -> None:
    det = detect(make_project({"pyproject.toml": "[project\n", "tests/": ""}))
    assert det.stack == "python"
    assert any("pyproject.toml is not valid TOML" in w for w in det.warnings)


# --------------------------------------------------------------------------- workflow


def test_uv_workflow(make_project) -> None:
    doc = workflow(make_project, PYTHON_UV)
    assert "astral-sh/setup-uv@v10.3.3" in uses(doc, "lint")
    lint = runs(doc, "lint")
    assert "uv run --no-sync ruff check --output-format=github ." in lint
    assert "uv run --no-sync ruff format --check --diff ." in lint
    assert "uv run --no-sync mypy src" in lint
    assert "--cov=src" in runs(doc, "test")
    assert "--cov-fail-under=80" in runs(doc, "test")
    assert "uvx pip-audit" in runs(doc, "audit")
    assert "uv build" in runs(doc, "build")


def test_pip_uses_version_file_and_cache(make_project) -> None:
    doc = workflow(make_project, PYTHON_PIP)
    setup = next(s for s in steps(doc, "test") if s.get("uses", "").startswith("actions/setup-python"))
    assert setup["with"]["python-version-file"] == ".python-version"
    assert setup["with"]["cache"] == "pip"
    assert "pip install -r requirements.txt -r requirements-dev.txt" in runs(doc, "test")
    assert "pip-audit --skip-editable" in runs(doc, "audit")


def test_matrix(make_project, tmp_path) -> None:
    text = render.render_workflow(config(make_project, PYTHON_UV, versions=["3.11", "3.12", "3.13"]))
    doc = load(text)
    test = doc["jobs"]["test"]
    assert test["strategy"]["matrix"]["python-version"] == ["3.11", "3.12", "3.13"]
    assert test["strategy"]["fail-fast"] is False
    assert "matrix.python-version" in test["name"]
    # Non-matrix jobs run on the newest version only.
    lint_setup = next(s for s in steps(doc, "lint") if "uses" in s and "setup-uv" in s["uses"])
    assert lint_setup["with"]["python-version"] == "3.13"
    actionlint(tmp_path, text)


def test_versions_are_quoted_so_310_stays_a_string(make_project) -> None:
    doc = workflow(make_project, PYTHON_UV, versions=["3.10", "3.11"])
    assert doc["jobs"]["test"]["strategy"]["matrix"]["python-version"] == ["3.10", "3.11"]


def test_poetry_runs_tools_through_poetry(make_project) -> None:
    doc = workflow(make_project, PYTHON_POETRY)
    assert "pipx install poetry" in runs(doc, "lint")
    assert "poetry run ruff check" in runs(doc, "lint")
    assert "poetry run pytest --cov=svc" in runs(doc, "test")


# --------------------------------------------------------------------------- frameworks


def test_django(make_project) -> None:
    det = detect(make_project(DJANGO))
    assert det.framework == "django"
    assert det.lint_tools == ["ruff", "django-check", "django-migrations"]
    assert det.test_runner == "django"
    assert det.source_dir == "."
    doc = workflow(make_project, DJANGO)
    assert "python manage.py makemigrations --check --dry-run" in runs(doc, "lint")
    assert "coverage run --source=. manage.py test" in runs(doc, "test")
    assert "coverage report --fail-under=80" in runs(doc, "test")


def test_django_with_pytest_django_keeps_pytest(make_project) -> None:
    det = detect(make_project({**DJANGO, "requirements.txt": "django\npytest-django\n"}))
    assert det.test_runner == "pytest"


def test_django_requires_manage_py(make_project) -> None:
    det = detect(make_project({"requirements.txt": "django-environ\nflask\n"}))
    assert det.framework == "flask"  # django-environ is not django


def test_fastapi(make_project) -> None:
    assert detect(make_project(FASTAPI)).framework == "fastapi"
