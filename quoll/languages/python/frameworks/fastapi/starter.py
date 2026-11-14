"""A new Python API: FastAPI, managed with uv, tested with pytest (TestClient), linted and formatted with ruff.

Copied from template/, then `uv add` resolves the current version of each dependency (FastAPI's version can
be chosen: `fastapi@0.115`). The Python version goes to .python-version, which the CI and the Dockerfile follow.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from quoll.languages.base import Starter, StarterOptions
from quoll.starters import from_template, install_locally, run

# Python version when none is asked for.
PYTHON_DEFAULT = "3.14"
DEV_DEPENDENCIES = ["pytest", "pytest-cov", "httpx", "ruff"]

_copy = from_template(
    Path(__file__).parent / "template",
    runtime_default=PYTHON_DEFAULT,
    # Stored under other names: they would apply to quoll's own repository.
    renamed={"python-version": ".python-version", "pyproject": "pyproject.toml"},
)


def create(directory: Path, options: StarterOptions) -> List[str]:
    _copy(directory, options)

    def uv(*args: str) -> None:
        # uv picks the Python of .python-version (and downloads it if needed).
        run(["uv", *args], directory, "python", options.runtime)

    uv("add", f"fastapi[standard]=={options.version}.*" if options.version else "fastapi[standard]")
    uv("add", "--dev", *DEV_DEPENDENCIES)
    return install_locally(directory, options.runtime, ["uv", "sync"], ".venv")


starter = Starter(
    name="fastapi", label="FastAPI", role="back", create=create, dev="uv run fastapi dev app/main.py",
    runtime="python", runtime_default=PYTHON_DEFAULT,
)
