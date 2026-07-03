from __future__ import annotations

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.python.detect import has_dependency
from quoll.languages.python.docker import PythonImage, find_app
from quoll.project import Project


class FlaskImage(PythonImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        warnings = []
        app = find_app(project, r"Flask\(")
        if app:
            target = f"{app[0]}:{app[1]}"
        else:
            factory = find_app(project, r"create_app\(")  # e.g. `app = create_app()` in wsgi.py
            target = f"{factory[0]}:{factory[1]}" if factory else "app:app"
            if not factory:
                warnings.append("No `app = Flask(...)` found — check docker.command in quoll.toml.")
        if not has_dependency(project, "gunicorn"):
            warnings.append("Add gunicorn to your dependencies: the image serves the app with it.")
        return DockerDefaults(port=8000, command=f"gunicorn {target} --bind 0.0.0.0:8000", warnings=warnings)
