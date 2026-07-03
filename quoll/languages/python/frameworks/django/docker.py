from __future__ import annotations

import re

from quoll.languages.base import Detection, DockerDefaults
from quoll.languages.python.detect import has_dependency
from quoll.languages.python.docker import PythonImage
from quoll.project import Project


class DjangoImage(PythonImage):
    def defaults(self, project: Project, det: Detection) -> DockerDefaults:
        m = re.search(r"DJANGO_SETTINGS_MODULE[\"']\s*,\s*[\"']([\w.]+)\.settings", project.read_text("manage.py"))
        module = m.group(1) if m else project.name.replace("-", "_")
        warnings = []
        if not has_dependency(project, "gunicorn"):
            warnings.append("Add gunicorn to your dependencies: the image serves the app with it.")
        if not has_dependency(project, "whitenoise"):
            warnings.append("Django doesn't serve static files in production — add WhiteNoise or serve them elsewhere.")
        return DockerDefaults(port=8000, command=f"gunicorn {module}.wsgi --bind 0.0.0.0:8000", warnings=warnings)
