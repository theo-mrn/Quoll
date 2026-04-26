from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict

import pytest

ProjectFactory = Callable[[Dict[str, str]], Path]


@pytest.fixture()
def make_project(tmp_path: Path) -> ProjectFactory:
    """Create a project from {relative path: content}. Dict/list contents are written as JSON."""

    def _make(files: Dict[str, object]) -> Path:
        root = tmp_path / "project"
        root.mkdir(exist_ok=True)
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith("/"):
                path.mkdir(exist_ok=True)
                continue
            path.write_text(json.dumps(content) if isinstance(content, (dict, list)) else str(content))
        return root

    return _make
