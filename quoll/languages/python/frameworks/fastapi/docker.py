from __future__ import annotations

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.python.detect import deps_text, has_dependency
from quoll.languages.python.docker import PythonImage, find_app
from quoll.project import Project


class FastapiImage(PythonImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        warnings = []
        app = find_app(project, r"FastAPI\(")
        if app is None:
            app = ("main", "app")
            warnings.append("No `app = FastAPI()` found — check docker.command in quoll.toml.")
        if not has_dependency(project, "uvicorn") and "fastapi[standard" not in deps_text(project):
            warnings.append("Add uvicorn (or fastapi[standard]) to your dependencies: the image runs the app with it.")
        module, name = app
        return DockerDefaults(
            port=8000, command=f"uvicorn {module}:{name} --host 0.0.0.0 --port 8000", warnings=warnings
        )
