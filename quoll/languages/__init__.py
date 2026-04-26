"""Language and framework plugins registry.

Built-in languages live in sub-packages of `quoll.languages`, each exposing a `language` object whose
`frameworks` live in its `frameworks/` sub-package. Third-party packages add languages or frameworks
(for any language) through entry points:

    [project.entry-points."quoll.languages"]
    elixir = "quoll_elixir:language"

    [project.entry-points."quoll.frameworks"]
    remix = "quoll_remix:framework"
"""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import Dict, List, Optional

from quoll.languages.base import DockerImage, Framework, Language, Starter
from quoll.project import Project

LANGUAGES_GROUP = "quoll.languages"
FRAMEWORKS_GROUP = "quoll.frameworks"

# Also the detection priority. Languages whose projects often carry a package.json for their front-end
# assets (Rails, Symfony, Laravel, Django...) come before node. C/C++ comes last: a CMakeLists.txt also builds the
# native parts of Python or Node packages.
_BUILTIN = ("go", "rust", "java", "dotnet", "php", "ruby", "python", "node", "cpp")

_languages: Dict[str, Language] = {}
_frameworks: Dict[str, List[Framework]] = {}
_loaded = False


def register(language: Language) -> None:
    if not isinstance(language, Language):
        raise TypeError(f"expected a quoll.languages.base.Language, got {type(language).__name__}")
    if language.name in _languages:
        raise ValueError(f"language '{language.name}' is already registered")
    _languages[language.name] = language
    _frameworks[language.name] = []
    for framework in language.frameworks:
        register_framework(framework)


def register_framework(framework: Framework) -> None:
    if not isinstance(framework, Framework):
        raise TypeError(f"expected a quoll.languages.base.Framework, got {type(framework).__name__}")
    if framework.language not in _languages:
        raise ValueError(f"framework '{framework.name}' targets unknown language '{framework.language}'")
    if any(f.name == framework.name for f in _frameworks[framework.language]):
        raise ValueError(f"framework '{framework.name}' is already registered for {framework.language}")
    _frameworks[framework.language].append(framework)


def available() -> List[Language]:
    """Registered languages, in detection priority order."""
    _load()
    return list(_languages.values())


def names() -> List[str]:
    return [lang.name for lang in available()]


def get(name: str) -> Language:
    _load()
    try:
        return _languages[name]
    except KeyError:
        raise KeyError(f"unknown language '{name}' (available: {', '.join(names())})") from None


def starters(role: str = "") -> List[Starter]:
    """Every starter of the registered languages and frameworks (for `role` only, when given)."""
    found = [s for lang in available() for owner in (lang, *frameworks(lang.name)) for s in owner.starters]
    return [s for s in found if not role or s.role == role]


def frameworks(language: str) -> List[Framework]:
    """Frameworks of `language`, in detection priority order."""
    _load()
    return list(_frameworks.get(language, []))


def get_framework(language: str, name: str) -> Optional[Framework]:
    return next((f for f in frameworks(language) if f.name == name), None)


def docker_image(language: str, framework: str = "") -> Optional[DockerImage]:
    """The framework's image when it has one, else the language's."""
    fw = get_framework(language, framework) if framework else None
    return (fw.docker if fw else None) or get(language).docker


def matching(project: Project) -> List[Language]:
    """Languages whose marker files are present, highest priority first."""
    return [lang for lang in available() if lang.matches(project)]


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for name in _BUILTIN:
        register(importlib.import_module(f"{__name__}.{name}").language)
    for group, add in ((LANGUAGES_GROUP, register), (FRAMEWORKS_GROUP, register_framework)):
        for ep in _entry_points(group):
            try:
                add(ep.load())
            except Exception as e:
                raise RuntimeError(f"quoll plugin '{ep.name}' ({ep.value}) failed to load: {e}") from e


def _entry_points(group: str) -> list:
    try:
        return list(entry_points(group=group))
    except TypeError:  # Python 3.9: entry_points() takes no arguments
        return list(entry_points().get(group, []))
