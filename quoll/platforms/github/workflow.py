"""Building blocks of GitHub Actions workflows: neutral steps rendered as workflow steps, emitted by quoll.yaml_dump."""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from quoll import yaml_dump
from quoll.ci.steps import Cache, Item, Step, step
from quoll.platforms.github.actions import ACTIONS, PINS
from quoll.yaml_dump import Commented


def render_steps(items: Sequence[Item], directory: str = ".") -> List[Dict[str, Any]]:
    """Workflow steps; caches of a project in `directory` get their paths from the repository root."""
    return [_cache(item, directory) if isinstance(item, Cache) else _step(item) for item in items]


def _step(s: Step) -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    if s.name:
        d["name"] = s.name
    if s.id:
        d["id"] = s.id
    if s.always:
        d["if"] = "${{ !cancelled() }}"
    if s.uses:
        d["uses"] = pin(s.uses)
        if s.with_:
            d["with"] = dict(s.with_)
    else:
        d["run"] = s.run
    env = {**s.env, **{name: f"${{{{ secrets.{name} }}}}" for name in s.secrets}}
    if env:
        d["env"] = env
    if s.optional:
        d["continue-on-error"] = True
    return d


def _cache(c: Cache, directory: str = ".") -> Dict[str, Any]:
    # Container platforms need `c.env` to keep tool caches in the project; runners use the default locations.
    def within(path: str) -> str:
        if directory == ".":
            return path
        return f"!{directory}/{path[1:]}" if path.startswith("!") else f"{directory}/{path}"

    prefix = f"{c.key}-${{{{ runner.os }}}}-"
    locked = prefix + _hash([within(f) for f in c.key_files]) if c.key_files else prefix.rstrip("-")
    with_: Dict[str, Any] = {"path": "\n".join(within(p) for p in c.paths)}
    if c.revision_files:
        with_["key"] = f"{locked}-{_hash([within(f) for f in c.revision_files])}"
        with_["restore-keys"] = f"{locked}-"
    else:
        with_["key"] = locked
    return {"name": c.name or f"Cache {c.key}", "uses": pin(ACTIONS["cache"]), "with": with_}


def pin(action: str) -> str:
    """owner/repo@<commit> # <version> for the actions quoll knows; others (plugins) as written."""
    if action not in PINS:
        return action
    path, version = action.split("@")
    return Commented(f"{path}@{PINS[action]}", version)


def _hash(patterns: Sequence[str]) -> str:
    return "${{ hashFiles(" + ", ".join(f"'{p}'" for p in patterns) + ") }}"


def checkout(**with_: Any) -> Step:
    return step("", uses=ACTIONS["checkout"], with_={k.replace("_", "-"): v for k, v in with_.items()})


def dump(doc: Dict[str, Any]) -> str:
    return yaml_dump.dump(doc, spaced=("jobs", "steps"))
