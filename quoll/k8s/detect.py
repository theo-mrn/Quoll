"""What quoll can tell about a project's deployment from its code."""
from __future__ import annotations

import os
import re
from pathlib import Path

_SOURCES = (".ts", ".js", ".mjs", ".py", ".go", ".rb", ".php", ".java", ".kt", ".cs", ".rs")
_SKIPPED = {"node_modules", "vendor", ".venv", "venv", "dist", "build", "target", ".git", "bin", "obj", "test", "tests"}
# Routes health checks usually answer on, most specific first.
_HEALTH = re.compile(r"""["'](/(?:healthz|health|livez|readyz|ping|up))["']""")
_MAX_FILES = 500


def health_path(project_dir: Path) -> str:
    """The health route the app's code declares, e.g. "/health"; empty when none is found."""
    seen = 0
    for directory, subdirectories, files in os.walk(project_dir):
        subdirectories[:] = sorted(d for d in subdirectories if d not in _SKIPPED and not d.startswith("."))
        for name in sorted(files):
            if not name.endswith(_SOURCES) or ".test." in name or ".spec." in name:
                continue
            seen += 1
            if seen > _MAX_FILES:
                return ""
            try:
                match = _HEALTH.search((Path(directory) / name).read_text(errors="ignore"))
            except OSError:
                continue
            if match:
                return match.group(1)
    return ""
