"""Python: pip, uv and poetry projects."""

from quoll.languages.base import Language
from quoll.languages.python.ci import PythonCI
from quoll.languages.python.detect import detect
from quoll.languages.python.docker import PythonImage
from quoll.languages.python.frameworks import django, fastapi, flask

language = Language(
    name="python",
    markers=("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile"),
    package_managers=("pip", "uv", "poetry"),
    lint_tools=("ruff", "ruff-format", "flake8", "black", "mypy"),
    test_runners=("pytest",),
    detect=detect,
    ci=PythonCI(),
    frameworks=(django.framework, fastapi.framework, flask.framework),
    docker=PythonImage(),
)
