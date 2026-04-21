"""Read-only view of a project directory, shared by every language plugin."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


class Project:
    """File helpers that never raise: missing files read as empty, unparsable ones add a warning."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.warnings: List[str] = []

    @property
    def name(self) -> str:
        return self.root.name

    def exists(self, *names: str) -> bool:
        return any((self.root / n).exists() for n in names)

    def is_dir(self, name: str) -> bool:
        return (self.root / name).is_dir()

    def glob(self, *patterns: str) -> List[Path]:
        return sorted(p for pattern in patterns for p in self.root.glob(pattern))

    def glob_any(self, *patterns: str) -> bool:
        return any(next(self.root.glob(p), None) is not None for p in patterns)

    def read_text(self, name: str) -> str:
        try:
            return (self.root / name).read_text()
        except OSError:
            return ""

    def read_toml(self, name: str) -> dict:
        if not self.exists(name):
            return {}
        try:
            with open(self.root / name, "rb") as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            self.warnings.append(f"{name} is not valid TOML ({e}) — detection is partial.")
            return {}

    def read_json(self, name: str) -> Any:
        if not self.exists(name):
            return {}
        try:
            return json.loads(self.read_text(name))
        except ValueError as e:
            self.warnings.append(f"{name} could not be parsed ({e}) — detection is partial.")
            return {}
